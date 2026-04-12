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
    printer_info: Optional[Dict[str, Any]] = None

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
    root_categories_json = json.dumps(context["root_categories"], indent=2)
    root_projects_json = json.dumps(context["root_projects"], indent=2)

    printer_transport = (req.printer_info or {}).get("transport")
    if req.printer_info and printer_transport != "offline":
        p_name = req.printer_info.get("name", "Unknown")
        p_media = req.printer_info.get("media_type", "continuous")
        p_width = req.printer_info.get("width_mm", context['engine_rules']['hardware_width_mm'])
        p_dpi = req.printer_info.get("dpi", 203)
        printer_status = f"CONNECTED PRINTER: '{p_name}' | Media Type: {p_media.upper()} | DPI: {p_dpi} | Max Print Width: {p_width}mm"
    elif req.printer_info:
        p_name = req.printer_info.get("name", "Unknown")
        p_media = req.printer_info.get("media_type", "continuous")
        p_width = req.printer_info.get("width_mm", context['engine_rules']['hardware_width_mm'])
        p_dpi = req.printer_info.get("dpi", 203)
        printer_status = (
            f"SELECTED PRINTER PROFILE (NOT CURRENTLY CONNECTED): '{p_name}' | "
            f"Media Type: {p_media.upper()} | DPI: {p_dpi} | Max Print Width: {p_width}mm. "
            "Use these exact layout constraints, but do not assume physical printing is currently available."
        )
    else:
        media_pref = context.get('intended_media_type', 'unknown')
        if media_pref == "continuous":
            printer_status = "NO PRINTER CONNECTED. User indicated they use CONTINUOUS rolls. Assume 203 DPI and 48mm/384px print head width. Use set_canvas_dimensions."
        elif media_pref == "pre-cut":
            printer_status = "NO PRINTER CONNECTED. User indicated they use PRE-CUT labels (e.g., Niimbot). Assume fixed media limits. ALWAYS use apply_preset."
        elif media_pref == "both":
            printer_status = "NO PRINTER CONNECTED. User uses BOTH rolls and pre-cut. Ask them which one they want for this design, or assume based on context."
        else:
            printer_status = "NO PRINTER CONNECTED. Media type UNKNOWN. You MUST ASK the user if they use 'pre-cut' labels or 'continuous' rolls before proceeding with sizing, UNLESS they explicitly mention it."
    
    sys_prompt = f"""You are an expert Label Design AI Assistant for CatLabel.
Your job is to act as a layout engineer, designing thermal printer labels and executing physical UI actions via tool calls.

CONTEXT:
- {context['engine_rules']['coordinate_system']}
- {context['engine_rules']['orientation_and_rotation']}
- Default Font: {context['global_default_font']}

HARDWARE & MEDIA CONSTRAINTS:
{printer_status}
- PRE-CUT MEDIA (e.g. Niimbot): Constrained to exact physical dimensions. MUST use `apply_preset`. Do not invent custom lengths.
- CONTINUOUS MEDIA (e.g. Generic Rolls): Tape is infinitely long. Use `set_canvas_dimensions` to create custom lengths.

AVAILABLE PRESETS:
{presets_json}

CRITICAL AGENT BEHAVIORS:
1. IMPLICIT CONFIRMATION: If you previously suggested a list of sizes, names, or a layout, and the user replies affirmatively (e.g., "ok", "yes", "sounds good", "the sizes are ok"), DO NOT ask them to provide the list again. Use the context from your own previous message and immediately execute the tools.
2. SIMULTANEOUS TOOL EXECUTION (CHAINING): To complete a user's request, you MUST call the necessary tools in a single response. For a batch job, call:
   a) `set_canvas_dimensions` OR `apply_preset` (to size the label)
   b) `layout_stacked_text` OR `layout_centered_text` (using {{{{ variable }}}} tags)
   c) `set_batch_records` (passing either the actual list of rows, a variables matrix for permutations, or a variables sequence for serialized labels)
   Do NOT stop halfway to ask for permission. Just do it.
3. FULL WIDTH OF ROLL: If the user wants to use the "full width" of the continuous roll, ensure the constrained dimension is set to {context['engine_rules']['hardware_width_px']} pixels (e.g., width=384 with `print_direction="across_tape"`, or height=384 with `print_direction="along_tape_banner"`).
4. MACROS FIRST: Always prefer the macro tools (`layout_centered_text`, `layout_stacked_text`) because they handle auto-scaling, wrapping, and centering flawlessly. Avoid manual `add_text_element` coordinate math unless strictly necessary.
5. COMMA-SEPARATED BATCHES (MATRIX): If a user provides multiple comma-separated lists for variables (e.g., "lengths: 3, 4" and "head: flat, countersunk"), you MUST call `set_batch_records` with the `variables_matrix` parameter. The backend will automatically generate the Cartesian product table for the UI.
6. SMART DATE VARIABLES: Do NOT manually calculate dates or create static batch records for dates. If the user asks for dates (like expiration dates), directly inject `{{{{ $date }}}}` (for today) or `{{{{ $date+7 }}}}` (for today + 7 days) directly into the `layout_centered_text` or `add_text_element` parameters. The rendering engine evaluates these dynamically.
7. NO EMOJIS: Do NOT use Unicode Emojis (e.g. 🚫📦🚀) in text items. Thermal printers are 1-bit monochrome and the font renderer will crash or draw empty boxes `[ ]`. Stick to standard text or ascii.

WORKFLOW EXAMPLES:
User: "Make M3 screw labels, 6, 8, and 10mm, standard list format."
Your Thought: Standard list format is Portrait. I will set the canvas height based on items.
Action: `set_canvas_dimensions(width=384, height=240, print_direction="across_tape")`

User: "Make a huge label for a 20cm shipping box. It needs to say FRAGILE."
Your Thought: 20cm is 200mm = 1600px. This requires a continuous roll. To fit 1600px length on a 384px print head, I must use banner mode.
Action:
1. `set_canvas_dimensions(width=1600, height=384, print_direction="along_tape_banner")`
2. `layout_centered_text(text="FRAGILE")`

User: "I need 50 asset tags with barcodes from AST-001 to AST-050."
Your Thought: I will create a layout with a barcode and text mapped to the `{{{{ asset }}}}` variable. Then I will use `set_batch_records` with `variables_sequence` to generate all 50 items instantly.
Action (Tool Calls in same response):
1. `apply_preset(preset_name="Standard Tape (Full Width 48mm)")`
2. `add_barcode_or_qrcode(type="barcode", data="{{{{ asset }}}}", x=20, y=50, width=344, height=80)`
3. `add_text_element(text="ID: {{{{ asset }}}}", x=0, y=150, align="center")`
4. `set_batch_records(variables_sequence={"variable_name": "asset", "prefix": "AST-", "start": 1, "end": 50, "padding": 3})`
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
                call_cost = litellm.completion_cost(completion_response=response)
                if call_cost:
                    total_cost += float(call_cost)
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
