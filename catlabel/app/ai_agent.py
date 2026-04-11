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
                is_active=True,
                vertex_region=getattr(old, "vertex_region", "") if old else ""
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

    if getattr(active_profile, "reasoning_effort", ""):
        kwargs["reasoning_effort"] = active_profile.reasoning_effort

    if not active_profile.use_env:
        if active_profile.provider == "vertex_ai":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as f:
                f.write(active_profile.api_key)
                kwargs["vertex_credentials"] = f.name
        else:
            kwargs["api_key"] = active_profile.api_key
            
        if active_profile.base_url:
            kwargs["api_base"] = active_profile.base_url

    if active_profile.provider == "vertex_ai" and getattr(active_profile, "vertex_region", ""):
        kwargs["vertex_location"] = active_profile.vertex_region

    context = get_agent_context()
    presets_json = json.dumps(context["standard_presets"], indent=2)
    
    sys_prompt = f"""You are an expert Label Design AI Assistant for CatLabel.
Your job is to act as a layout engineer, designing thermal printer labels and executing physical UI actions.

CONTEXT:
- Hardware Print Width: {context['engine_rules']['hardware_width_px']} pixels
- 1 mm = 8 pixels. ALWAYS use pixels for canvas dimensions and positions.
- Default Font: {context['global_default_font']}

AVAILABLE PRESETS:
{presets_json}

RULES:
1. Single Label Canvas: Your canvas should ALWAYS represent the dimensions of a SINGLE label. Discrete pre-cut or gap-sensed labels (for example Niimbot D11/B1 stickers) MUST be one label per page. Do NOT multiply the height to stack multiple labels. Use the `apply_preset` tool whenever the user mentions a standard size (e.g., Niimbot 12x40, A6, Gridfinity).
2. Standard Text: Use `add_text_element` for fast native rendering.
3. Custom HTML/CSS/SVG: You can generate rich graphics using `add_html_element`. You MUST use inline styles or embedded <style>. Use width:100% and height:100% with box-sizing:border-box on the root. Do not load external assets.
4. Series / Multiple Labels: If the user asks for a "series", "set", or "multiple" labels (e.g., sizes, names), DO NOT stack them vertically by calculating Y offsets. INSTEAD:
   - Step 1: Call `apply_preset` or `set_canvas_dimensions` for a SINGLE label.
   - Step 2: Add your template elements using `{{{{ variable_name }}}}` syntax (e.g. "M3 x {{{{ size }}}}").
   - Step 3: Call `multiply_workspace_with_variables` with the list of records to generate separate pages.
5. splitMode CRITICAL: NEVER use `splitMode: true` unless the user explicitly asks for a giant multi-strip mural/decal or a continuous banner.
6. Vision Feedback: If enabled, you will automatically be shown an image of the active canvas page before your final response. Use it to verify if your HTML or text overlaps/aligns correctly.
7. Be highly proactive. Do not give code back to the user; execute the tools directly.
"""

    messages = [{"role": "system", "content": sys_prompt}] + req.messages
    canvas_state_copy = dict(req.canvas_state)

    try:
        MAX_ITERATIONS = 15
        iteration = 0
        new_messages = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0
        
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

            usage = getattr(response, "usage", None)
            if usage:
                if isinstance(usage, dict):
                    total_prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
                    total_completion_tokens += int(usage.get("completion_tokens", 0) or 0)
                else:
                    total_prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
                    total_completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

            try:
                total_cost += float(litellm.completion_cost(completion_response=response) or 0.0)
            except Exception:
                pass

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
            "canvas_state": canvas_state_copy,
            "usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
                "cost": total_cost
            }
        }
        
    except Exception as e:
        logger.exception("Error during Litellm chat generation.")
        return {"error": str(e), "canvas_state": req.canvas_state}
