import copy
import json
import os
import tempfile
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union
from sqlmodel import Session, select
import litellm

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] AI_AGENT: %(message)s")

from .models import AIConfig, AIConversation, AIProvider, AIModelConfig
from .ai_tools import TOOLS_SCHEMA, execute_tool

router = APIRouter(prefix="/api/ai", tags=["AI Agent"])

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    canvas_state: Dict[str, Any]
    mac_address: Optional[str] = None
    printer_info: Optional[Dict[str, Any]] = None
    current_canvas_b64: Optional[str] = None

class ModelDTO(BaseModel):
    id: Optional[Union[int, str]] = None
    name: str
    model_name: str
    vision_capable: bool
    reasoning_effort: str
    is_active: bool

class ProviderDTO(BaseModel):
    id: Optional[Union[int, str]] = None
    name: str
    provider: str
    api_key: str
    base_url: str
    use_env: bool
    vertex_region: str
    models: List[ModelDTO] = []

def serialize_msg(msg) -> Dict[str, Any]:
    if hasattr(msg, "model_dump"): d = msg.model_dump(exclude_none=True)
    elif hasattr(msg, "dict"): d = msg.dict(exclude_none=True)
    else: d = dict(msg)
    allowed_keys = {"role", "content", "name", "tool_calls", "tool_call_id"}
    clean_d = {k: v for k, v in d.items() if k in allowed_keys}
    if clean_d.get("role") == "assistant" and "content" not in clean_d:
        clean_d["content"] = None
    return clean_d


@router.get("/config")
def get_providers():
    from .server import engine
    with Session(engine) as session:
        providers = session.exec(select(AIProvider)).all()
        if not providers:
            old = session.get(AIConfig, 1)
            provider = AIProvider(
                name="Default Provider",
                provider=old.provider if old else "openai",
                api_key=old.api_key if old else "",
                base_url=old.base_url if old else "",
                use_env=old.use_env if old else False,
                vertex_region=getattr(old, "vertex_region", "") if old else "",
            )
            session.add(provider)
            session.commit()
            session.refresh(provider)

            model_name = old.model_name if old and old.model_name else "gpt-4o"
            model = AIModelConfig(
                provider_id=provider.id,
                name=model_name.split("/")[-1],
                model_name=model_name,
                vision_capable=True,
                is_active=True,
            )
            session.add(model)
            session.commit()
            providers = [provider]

        result = []
        for provider in providers:
            models = session.exec(select(AIModelConfig).where(AIModelConfig.provider_id == provider.id)).all()
            provider_dict = provider.model_dump() if hasattr(provider, "model_dump") else provider.dict()
            provider_dict["models"] = [
                model.model_dump() if hasattr(model, "model_dump") else model.dict()
                for model in models
            ]
            result.append(provider_dict)
        return result

@router.post("/config")
def save_provider(payload: ProviderDTO):
    from .server import engine
    with Session(engine) as session:
        if any(model.is_active for model in payload.models):
            all_models = session.exec(select(AIModelConfig)).all()
            for model in all_models:
                if model.is_active:
                    model.is_active = False
                    session.add(model)

        provider_data = (
            payload.model_dump(exclude={"id", "models"})
            if hasattr(payload, "model_dump")
            else payload.dict(exclude={"id", "models"})
        )

        if isinstance(payload.id, int):
            provider = session.get(AIProvider, payload.id)
            if provider:
                for key, value in provider_data.items():
                    setattr(provider, key, value)
            else:
                provider = AIProvider(**provider_data)
        else:
            provider = AIProvider(**provider_data)

        session.add(provider)
        session.commit()
        session.refresh(provider)

        keep_model_ids = []
        for model_data in payload.models:
            model_dict = (
                model_data.model_dump(exclude={"id"})
                if hasattr(model_data, "model_dump")
                else model_data.dict(exclude={"id"})
            )

            if isinstance(model_data.id, int):
                model_db = session.get(AIModelConfig, model_data.id)
                if model_db:
                    for key, value in model_dict.items():
                        setattr(model_db, key, value)
                    model_db.provider_id = provider.id
                    session.add(model_db)
                    session.commit()
                    keep_model_ids.append(model_db.id)
                else:
                    new_model = AIModelConfig(**model_dict, provider_id=provider.id)
                    session.add(new_model)
                    session.commit()
                    session.refresh(new_model)
                    keep_model_ids.append(new_model.id)
            else:
                new_model = AIModelConfig(**model_dict, provider_id=provider.id)
                session.add(new_model)
                session.commit()
                session.refresh(new_model)
                keep_model_ids.append(new_model.id)

        existing_models = session.exec(select(AIModelConfig).where(AIModelConfig.provider_id == provider.id)).all()
        for existing_model in existing_models:
            if existing_model.id not in keep_model_ids:
                session.delete(existing_model)
        session.commit()

        return {"status": "ok", "id": provider.id}

@router.delete("/config/{provider_id}")
def delete_provider(provider_id: int):
    from .server import engine
    with Session(engine) as session:
        provider = session.get(AIProvider, provider_id)
        if provider:
            models = session.exec(select(AIModelConfig).where(AIModelConfig.provider_id == provider.id)).all()
            for model in models:
                session.delete(model)
            session.delete(provider)
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
        active_model = session.exec(select(AIModelConfig).where(AIModelConfig.is_active == True)).first()
        if not active_model:
            active_model = session.exec(select(AIModelConfig)).first()

        if not active_model:
            raise HTTPException(status_code=400, detail="No AI models configured. Please configure an AI Provider and Model in settings.")

        active_provider = session.get(AIProvider, active_model.provider_id)
        if not active_provider:
            raise HTTPException(status_code=400, detail="The active AI model is linked to a missing provider. Please update your AI configuration.")

    kwargs = {
        "model": f"{active_provider.provider}/{active_model.model_name}" if active_provider.provider != "custom" else active_model.model_name,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto"
    }

    if getattr(active_model, "reasoning_effort", ""):
        kwargs["reasoning_effort"] = active_model.reasoning_effort

    if not active_provider.use_env:
        if active_provider.provider == "vertex_ai":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as f:
                f.write(active_provider.api_key)
                kwargs["vertex_credentials"] = f.name
        else:
            kwargs["api_key"] = active_provider.api_key

        if active_provider.base_url:
            kwargs["api_base"] = active_provider.base_url

    if active_provider.provider == "vertex_ai" and getattr(active_provider, "vertex_region", ""):
        kwargs["vertex_location"] = active_provider.vertex_region

    context = get_agent_context()
    presets_json = json.dumps(context["standard_presets"], indent=2)
    templates_json = json.dumps(context["available_templates"], indent=2)
    root_categories_json = json.dumps(context["root_categories"], indent=2)
    root_projects_json = json.dumps(context["root_projects"], indent=2)

    media_pref = context.get('intended_media_type', 'unknown')

    # Determine the strict media constraint for the AI
    p_media = "unknown"
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
        printer_status = f"SELECTED OFFLINE PRINTER: '{p_name}' | Media Type: {p_media.upper()} | DPI: {p_dpi} | Max Print Width: {p_width}mm."
    else:
        if media_pref in ["continuous", "pre-cut"]:
            p_media = media_pref
            printer_status = f"NO PRINTER CONNECTED. User default media type preference is: {p_media.upper()}."
        else:
            printer_status = "NO PRINTER CONNECTED. Media type UNKNOWN. Ask the user if they use 'pre-cut' labels or 'continuous' rolls."
    
    sys_prompt = f"""You are an expert Label Design AI Assistant for CatLabel.
Your job is to act as a layout engineer, designing thermal printer labels and executing physical UI actions via tool calls.

CONTEXT:
- {context['engine_rules']['coordinate_system']}
- Default Font: {context['global_default_font']}

HARDWARE STATUS:
{printer_status}

CRITICAL MEDIA TYPE RULES (MUST OBEY):
1. CONTINUOUS MEDIA (Generic Rolls): Tape feeds infinitely. You MUST use presets marked media_type="continuous".
2. PRE-CUT MEDIA (Niimbot): Fixed boundaries. You MUST use presets marked media_type="pre-cut". Pre-cut labels are fed sideways, so they are almost always rotated.

AVAILABLE PRESETS (Use apply_preset):
{presets_json}

AVAILABLE TEMPLATES (Use apply_template):
{templates_json}

CRITICAL LAYOUT STRATEGY (WYSIWYG SYNERGY):
For NEW labels, you MUST use `apply_template` passing the exact `template_id` and filling the `params` object based on the fields listed above.
The system will automatically convert this into perfectly measured, editable items on the user's canvas based on the current preset's Aspect Ratio!

GRANULAR PARSING (VERY IMPORTANT):
When a user provides unstructured data, you MUST parse it into the specific granular fields of the template.
Example: For a Price Tag, if the user says "Hammer £24.99", you must split it: currency_symbol="£", price_main="24", price_cents="99", product_name="Hammer".

WARNING: DO NOT guess X/Y coordinates if a template exists. Always use `apply_template`. 
If you absolutely MUST build a custom layout using `add_text_element`, you MUST rely on `fit_to_width: true` and provide a strict `width` and `height` (a Bounding Box). The layout engine will perform a binary search to perfectly scale the text to fit your box. Never leave text unconstrained.

STYLING RULES:
You can use `color: "white"` and `bgColor: "black"` to create inverted emphasis tags.
You can use `italic: true` and `underline: true` to format text. 
You can rotate elements using `rotation: 90` (or 180, 270) if you need text to run vertically on the canvas.

BATCH PRINTING PARADIGM:
Do NOT create multiple pages for a list of data. To print a batch:
1. Call `apply_template` placing `{{{{ variables }}}}` inside the params (e.g., `params: {{"product_name": "{{{{ name }}}}"}}`).
2. Call `set_batch_records` passing the array of data. The frontend handles generating the copies automatically!

WORKFLOW EXAMPLES:
User: "Make a price tag for a Hammer, $15.99."
Action:
1. `apply_preset(preset_name="Roll: Standard Square (48x48mm)")`
2. `apply_template(template_id="price_tag", params={{"currency_symbol": "$", "price_main": "15", "price_cents": "99", "product_name": "Hammer", "barcode": "123456"}})`

User: "I have a continuous roll. Make 5 small inventory tags: Desk, Chair, Lamp, Monitor, Keyboard."
Action (All in one turn):
1. `apply_preset(preset_name="Roll: Narrow Tag (48x15mm)")`
2. `apply_template(template_id="inventory_tag", params={{"department": "OFFICE", "title": "{{{{ item }}}}", "sku": "SKU-{{{{ item }}}}", "code_data": "ID-{{{{ item }}}}", "code_type": "qrcode"}})`
3. `set_batch_records(variables_list=[{{"item": "Desk"}}, {{"item": "Chair"}}, {{"item": "Lamp"}}, {{"item": "Monitor"}}, {{"item": "Keyboard"}}])`
"""

    messages = [{"role": "system", "content": sys_prompt}] + req.messages
    canvas_state_copy = copy.deepcopy(req.canvas_state)

    if active_model.vision_capable and req.current_canvas_b64:
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") != "user":
                continue

            original_content = messages[i].get("content", "")
            if isinstance(original_content, str):
                messages[i]["content"] = [
                    {
                        "type": "text",
                        "text": original_content + "\n\n[SYSTEM AUTO-INJECT] Current visual render of the canvas. Evaluate your layout:",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{req.current_canvas_b64}"},
                    },
                ]
            break

    try:
        MAX_ITERATIONS = 15
        iteration = 0
        new_messages = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0
        response = None

        logger.info("Starting LLM Agent loop using model: %s", kwargs.get("model"))

        while iteration < MAX_ITERATIONS:
            iteration += 1

            response = litellm.completion(messages=messages, **kwargs)

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

            if hasattr(resp_msg, "tool_calls") and resp_msg.tool_calls:
                for tool_call in resp_msg.tool_calls:
                    if isinstance(tool_call, dict):
                        fn_name = tool_call.get("function", {}).get("name")
                        args_str = tool_call.get("function", {}).get("arguments", "{}")
                        tc_id = tool_call.get("id")
                    else:
                        fn_name = tool_call.function.name
                        args_str = tool_call.function.arguments
                        tc_id = tool_call.id

                    logger.info("➡️ Agent requested Tool Call: %s", fn_name)
                    logger.info("   Arguments: %s", args_str)

                    try:
                        fn_args = json.loads(args_str)
                        tool_result = execute_tool(fn_name, fn_args, canvas_state_copy)
                        logger.info("✅ Tool Result: %s", tool_result)
                    except Exception as e:
                        tool_result = f"Error executing tool {fn_name}: {str(e)}"
                        logger.error("❌ Tool Error: %s", tool_result)

                    tool_msg = {
                        "role": "tool",
                        "name": fn_name,
                        "tool_call_id": tc_id,
                        "content": str(tool_result),
                    }
                    messages.append(tool_msg)
                    new_messages.append(tool_msg)
            else:
                logger.info("Agent finished turn. Total Cost so far: $%.4f", total_cost)
                break

        return {
            "new_messages": new_messages,
            "canvas_state": canvas_state_copy,
            "usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
                "cost": total_cost,
                "model_used": getattr(response, "model", kwargs.get("model")) if response is not None else kwargs.get("model"),
            },
        }

    except Exception as e:
        logger.exception("Error during Litellm chat generation.")
        return {"error": str(e), "canvas_state": req.canvas_state}
