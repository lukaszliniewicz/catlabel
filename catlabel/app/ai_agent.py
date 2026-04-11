import json
import os
import tempfile
import logging
import base64
from io import BytesIO
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select
import litellm

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] AI_AGENT: %(message)s")

from .models import AIConfig, AIAgentProfile, AIConversation
from .ai_tools import TOOLS_SCHEMA, execute_tool
from ..rendering.template import render_template

router = APIRouter(prefix="/api/ai", tags=["AI Agent"])

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    canvas_state: Dict[str, Any]
    mac_address: Optional[str] = None

def serialize_msg(msg) -> Dict[str, Any]:
    if hasattr(msg, "model_dump"): d = msg.model_dump(exclude_none=True)
    elif hasattr(msg, "dict"): d = msg.dict(exclude_none=True)
    else: d = dict(msg)
    allowed_keys = {"role", "content", "name", "tool_calls", "tool_call_id"}
    clean_d = {k: v for k, v in d.items() if k in allowed_keys}
    if clean_d.get("role") == "assistant" and "content" not in clean_d:
        clean_d["content"] = None
    return clean_d

def _preview_canvas_state(canvas_state):
    preview_state = dict(canvas_state or {})
    items = list(preview_state.get("items", []) or [])
    if not items:
        preview_state["items"] = []
        return preview_state

    page_indexes = sorted({int(item.get("pageIndex", 0) or 0) for item in items})
    current_page = preview_state.get("currentPage", 0)
    try:
        current_page = int(current_page or 0)
    except Exception:
        current_page = 0

    if current_page not in page_indexes:
        current_page = page_indexes[0]

    preview_state["items"] = [
        item for item in items
        if int(item.get("pageIndex", 0) or 0) == current_page
    ]
    return preview_state

def get_canvas_b64(canvas_state, default_font):
    """Renders the active canvas page to base64 JPEG for Vision models."""
    try:
        preview_state = _preview_canvas_state(canvas_state)
        img = render_template(preview_state, {}, default_font=default_font)
        buf = BytesIO()
        # Max resolution bound to save tokens, RGB conversion for JPEG
        img.convert("RGB").save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.error(f"Canvas render failed for vision: {e}")
        return None

@router.get("/config")
def get_profiles():
    from .server import engine
    with Session(engine) as session:
        profiles = session.exec(select(AIAgentProfile)).all()
        if not profiles:
            old = session.get(AIConfig, 1)
            p = AIAgentProfile(
                name="Default Profile",
                provider=old.provider if old else "openai",
                model_name=old.model_name if old else "gpt-4o",
                api_key=old.api_key if old else "",
                base_url=old.base_url if old else "",
                use_env=old.use_env if old else False,
                vision_capable=True,
                is_active=True
            )
            session.add(p)
            session.commit()
            session.refresh(p)
            profiles = [p]
        return profiles

@router.post("/config")
def save_profile(profile: AIAgentProfile):
    from .server import engine
    with Session(engine) as session:
        if profile.is_active:
            # Deactivate all others
            all_p = session.exec(select(AIAgentProfile)).all()
            for p in all_p:
                if p.id != profile.id:
                    p.is_active = False
                    session.add(p)

        if profile.id is not None:
            existing = session.get(AIAgentProfile, profile.id)
            if existing:
                if hasattr(profile, "model_dump"):
                    profile_data = profile.model_dump(exclude_unset=True)
                else:
                    profile_data = profile.dict(exclude_unset=True)

                for key, value in profile_data.items():
                    setattr(existing, key, value)
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing

        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile

@router.delete("/config/{profile_id}")
def delete_profile(profile_id: int):
    from .server import engine
    with Session(engine) as session:
        p = session.get(AIAgentProfile, profile_id)
        if p:
            session.delete(p)
            session.commit()
        return {"status": "ok"}

@router.get("/history")
def get_histories():
    from .server import engine
    with Session(engine) as session:
        convos = session.exec(select(AIConversation).order_by(AIConversation.updated_at.desc())).all()
        return [{"id": c.id, "title": c.title, "updated_at": c.updated_at} for c in convos]

@router.get("/history/{conv_id}")
def get_history(conv_id: int):
    from .server import engine
    with Session(engine) as session:
        c = session.get(AIConversation, conv_id)
        if not c: raise HTTPException(status_code=404)
        return {"id": c.id, "title": c.title, "messages": json.loads(c.messages_json)}

@router.post("/history")
def create_history(data: dict):
    from .server import engine
    with Session(engine) as session:
        title = data.get("title", "New Conversation")
        messages = data.get("messages", [])
        c = AIConversation(title=title, messages_json=json.dumps(messages))
        session.add(c)
        session.commit()
        session.refresh(c)
        return {"id": c.id}

@router.put("/history/{conv_id}")
def update_history(conv_id: int, data: dict):
    from .server import engine
    with Session(engine) as session:
        c = session.get(AIConversation, conv_id)
        if not c: raise HTTPException(status_code=404)
        if "title" in data: c.title = data["title"]
        if "messages" in data: c.messages_json = json.dumps(data["messages"])
        c.updated_at = datetime.utcnow()
        session.add(c)
        session.commit()
        return {"status": "ok"}

@router.delete("/history/{conv_id}")
def delete_history(conv_id: int):
    from .server import engine
    with Session(engine) as session:
        c = session.get(AIConversation, conv_id)
        if c:
            session.delete(c)
            session.commit()
        return {"status": "ok"}

@router.post("/chat")
def chat_with_agent(req: ChatRequest):
    from .server import engine, get_agent_context
    with Session(engine) as session:
        active_profile = session.exec(select(AIAgentProfile).where(AIAgentProfile.is_active == True)).first()
        if not active_profile:
            active_profile = session.exec(select(AIAgentProfile)).first() or AIAgentProfile()

    kwargs = {
        "model": f"{active_profile.provider}/{active_profile.model_name}" if active_profile.provider != "custom" else active_profile.model_name,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto"
    }

    if not active_profile.use_env:
        if active_profile.provider == "vertex_ai":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as f:
                f.write(active_profile.api_key)
                kwargs["vertex_credentials"] = f.name
        else:
            kwargs["api_key"] = active_profile.api_key
            
        if active_profile.base_url:
            kwargs["api_base"] = active_profile.base_url

    context = get_agent_context()
    
    sys_prompt = f"""You are an expert Label Design AI Assistant for CatLabel.
Your job is to act as a layout engineer, designing thermal printer labels and executing physical UI actions.

CONTEXT:
- Hardware Print Width: {context['engine_rules']['hardware_width_px']} pixels
- 1 mm = 8 pixels. ALWAYS use pixels for canvas dimensions and positions.
- Default Font: {context['global_default_font']}

RULES:
1. Standard Text: Use `add_text_element` for fast native rendering.
2. Custom HTML/CSS/SVG: You can generate rich graphics using `add_html_element`. You MUST use inline styles or embedded <style>. Use width:100% and height:100% with box-sizing:border-box on the root. Do not load external assets.
3. Group Alignment: If you create multiple elements (text, html, etc) that should be centered together, call `align_group` passing their IDs.
4. Multi-Page Layouts: If the user wants multiple distinct labels visible in the editor, use `multiply_workspace_with_variables` so each variation is placed on its own page. You MUST provide a populated `variables_list`. Do not pass empty arguments.
5. Vision Feedback: If enabled, you will automatically be shown an image of the active canvas page before your final response. Use it to verify if your HTML or text overlaps/aligns correctly.
6. Be highly proactive. Do not give code back to the user; execute the tools directly.
7. Batch Variations: If the user wants multiple label variants driven by structured data (e.g., "a bunch of sizes", "different lengths"), use `set_batch_records` providing a robust list of standard variations in `variables_list`. You MUST invent the data if the user doesn't specify (e.g., for M3 lengths, use 4, 6, 8, 10, 12, 16, 20). DO NOT call the tool with empty arguments!
"""

    messages = [{"role": "system", "content": sys_prompt}] + req.messages
    canvas_state_copy = dict(req.canvas_state)

    try:
        MAX_ITERATIONS = 15
        iteration = 0
        new_messages = []
        
        while iteration < MAX_ITERATIONS:
            iteration += 1
            
            # --- VISION TRANSIENT INJECTION ---
            temp_messages = messages.copy()
            if active_profile.vision_capable:
                b64 = get_canvas_b64(canvas_state_copy, context['global_default_font'])
                if b64:
                    temp_messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "[SYSTEM AUTO-INJECT] Current visual render of the canvas. Evaluate your layout:"},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                        ]
                    })
            
            response = litellm.completion(messages=temp_messages, **kwargs)
            resp_msg = response.choices[0].message
            resp_dict = serialize_msg(resp_msg)
            
            messages.append(resp_dict)
            new_messages.append(resp_dict)
            
            if hasattr(resp_msg, 'tool_calls') and resp_msg.tool_calls:
                for tool_call in resp_msg.tool_calls:
                    if isinstance(tool_call, dict):
                        fn_name = tool_call.get("function", {}).get("name")
                        args_str = tool_call.get("function", {}).get("arguments", "{}")
                        tc_id = tool_call.get("id")
                    else:
                        fn_name = tool_call.function.name
                        args_str = tool_call.function.arguments
                        tc_id = tool_call.id
                        
                    try:
                        fn_args = json.loads(args_str)
                        tool_result = execute_tool(fn_name, fn_args, canvas_state_copy)
                    except Exception as e:
                        tool_result = f"Error executing tool {fn_name}: {str(e)}"
                    
                    tool_msg = {
                        "role": "tool",
                        "name": fn_name,
                        "tool_call_id": tc_id,
                        "content": str(tool_result)
                    }
                    messages.append(tool_msg)
                    new_messages.append(tool_msg)
            else:
                break
                
        return {
            "new_messages": new_messages,
            "canvas_state": canvas_state_copy
        }
        
    except Exception as e:
        logger.exception("Error during Litellm chat generation.")
        return {"error": str(e), "canvas_state": req.canvas_state}
