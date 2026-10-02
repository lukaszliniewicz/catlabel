import copy
import json
import logging
import tempfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import litellm
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, NaiveDatetime
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, col, select

from ..core.models import AIConfig, AIConversation, AIModelConfig, AIProvider
from ..services.ai_secrets import (
    known_environment_secrets,
    redact_secrets,
    secret_values,
)
from ..services.ai_tools import TOOLS_SCHEMA, execute_tool

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] AI_AGENT: %(message)s"
)


router = APIRouter(prefix="/api/ai", tags=["AI Agent"])


class AITraceLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int | None = Field(default=None, index=True)
    timestamp: NaiveDatetime = Field(default_factory=datetime.utcnow)
    model_used: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    request_messages_json: str = "[]"
    response_message_json: str = "{}"


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    canvas_state: dict[str, Any]
    mac_address: str | None = None
    printer_info: dict[str, Any] | None = None
    current_canvas_b64: str | None = None
    conv_id: int | None = None


class ManualPromptRequest(BaseModel):
    intent: str
    canvas_state: dict[str, Any]
    mac_address: str | None = None
    printer_info: dict[str, Any] | None = None


class ManualExecuteRequest(BaseModel):
    tool_calls: list[dict[str, Any]]
    canvas_state: dict[str, Any]


class ModelDTO(BaseModel):
    id: int | str | None = None
    name: str
    model_name: str
    vision_capable: bool
    reasoning_effort: str
    is_active: bool


class ProviderDTO(BaseModel):
    id: int | str | None = None
    name: str
    provider: str
    api_key: str | None = None
    clear_api_key: bool = False
    base_url: str
    use_env: bool
    vertex_region: str
    models: list[ModelDTO] = []


def serialize_msg(msg) -> dict[str, Any]:
    if hasattr(msg, "model_dump"):
        d = msg.model_dump(exclude_none=True)
    elif hasattr(msg, "dict"):
        d = msg.dict(exclude_none=True)
    else:
        d = dict(msg)
    allowed_keys = {"role", "content", "name", "tool_calls", "tool_call_id"}
    clean_d = {k: v for k, v in d.items() if k in allowed_keys}
    if clean_d.get("role") == "assistant" and "content" not in clean_d:
        clean_d["content"] = None
    return clean_d


def sanitize_trace_data(data: Any, secrets: Iterable[str] = ()) -> Any:
    """Redact secrets and truncate long image data, including encoded tool JSON."""

    def truncate(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: truncate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [truncate(item) for item in value]
        if isinstance(value, str):
            if value.startswith("data:image/") and len(value) > 100:
                return value[:50] + f"...[TRUNCATED BASE64, len={len(value)}]"
            if value.strip().startswith(("{", "[")):
                try:
                    parsed = json.loads(value)
                except ValueError:
                    pass
                else:
                    if isinstance(parsed, (dict, list)):
                        return json.dumps(truncate(parsed))
        return value

    return truncate(redact_secrets(data, secrets))


def _saved_secrets(session: Session) -> tuple[str, ...]:
    values = [provider.api_key for provider in session.exec(select(AIProvider)).all()]
    values.extend(config.api_key for config in session.exec(select(AIConfig)).all())
    return secret_values(values) + known_environment_secrets()


def _redact_stored_observability(session: Session, secrets: Iterable[str]) -> None:
    """Scrub retained observations before retiring credentials, in their transaction."""
    for conversation in session.exec(select(AIConversation)).all():
        conversation.title = redact_secrets(conversation.title, secrets)
        conversation.messages_json = redact_secrets(
            conversation.messages_json, secrets, redact_fields=False
        )
        session.add(conversation)
    for trace in session.exec(select(AITraceLog)).all():
        trace.model_used = redact_secrets(trace.model_used, secrets)
        trace.request_messages_json = redact_secrets(
            trace.request_messages_json, secrets
        )
        trace.response_message_json = redact_secrets(
            trace.response_message_json, secrets
        )
        session.add(trace)


def migrate_legacy_provider(engine: Engine) -> None:
    """Copy legacy configuration once, atomically, without deleting recovery data."""
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS catlabel_migrations (name TEXT PRIMARY KEY)"
        )
        if connection.exec_driver_sql(
            "SELECT name FROM catlabel_migrations WHERE name = ?", ("ai_providers_v1",)
        ).first():
            return
        with Session(bind=connection) as session:
            if not session.exec(select(AIProvider)).first():
                old = session.get(AIConfig, 1)
                if old:
                    provider = AIProvider(
                        name="Default Provider",
                        provider=old.provider,
                        api_key=old.api_key,
                        base_url=old.base_url,
                        use_env=old.use_env,
                        vertex_region=old.vertex_region,
                    )
                    session.add(provider)
                    session.flush()
                    assert provider.id is not None
                    model_name = old.model_name or "gpt-4o"
                    session.add(
                        AIModelConfig(
                            provider_id=provider.id,
                            name=model_name.split("/")[-1],
                            model_name=model_name,
                            vision_capable=True,
                            is_active=True,
                        )
                    )
                    session.flush()
            connection.exec_driver_sql(
                "INSERT INTO catlabel_migrations (name) VALUES (?)",
                ("ai_providers_v1",),
            )


def _resolve_printer_status(
    printer_info: dict[str, Any] | None, context: dict[str, Any]
) -> str:
    media_pref = context.get("intended_media_type", "unknown")
    printer_transport = (printer_info or {}).get("transport")

    if printer_info and printer_transport != "offline":
        p_name = printer_info.get("name", "Unknown")
        p_media = printer_info.get("media_type", "continuous")
        p_width = printer_info.get(
            "width_mm", context["engine_rules"]["hardware_width_mm"]
        )
        p_dpi = printer_info.get("dpi", 203)
        return f"CONNECTED PRINTER: '{p_name}' | Media Type: {p_media.upper()} | DPI: {p_dpi} | Max Print Width: {p_width}mm"

    if printer_info:
        p_name = printer_info.get("name", "Unknown")
        p_media = printer_info.get("media_type", "continuous")
        p_width = printer_info.get(
            "width_mm", context["engine_rules"]["hardware_width_mm"]
        )
        p_dpi = printer_info.get("dpi", 203)
        return f"SELECTED OFFLINE PRINTER: '{p_name}' | Media Type: {p_media.upper()} | DPI: {p_dpi} | Max Print Width: {p_width}mm. Tailor your design constraints strictly to this offline profile."

    if media_pref in ["continuous", "pre-cut"]:
        return f"NO PRINTER CONNECTED. Assume a generic continuous roll with a hardware width of 48mm (384px in canvas coordinates) unless the user specifies otherwise. User default media type preference is: {media_pref.upper()}."

    return "NO PRINTER CONNECTED. Assume a generic continuous roll with a hardware width of 48mm (384px in canvas coordinates) unless the user specifies otherwise. If their request implies a specific label type (e.g., a tiny cable flag), ask them to clarify or use a standard preset."


def _sanitize_manual_canvas_state(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {k: _sanitize_manual_canvas_state(v, k) for k, v in value.items()}

    if isinstance(value, list):
        return [_sanitize_manual_canvas_state(item, key) for item in value]

    if isinstance(value, str):
        if value.startswith("data:image/"):
            return f"[OMITTED IMAGE DATA len={len(value)}]"

        if key in {"htmlContent", "html", "custom_html"}:
            trimmed = value.strip()
            if len(trimmed) > 2000:
                return trimmed[:1000] + f"...[TRUNCATED HTML len={len(trimmed)}]"
            return trimmed

        if len(value) > 4000:
            return value[:1000] + f"...[TRUNCATED TEXT len={len(value)}]"

    return value


def _normalize_manual_tool_call(call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(call, dict):
        raise ValueError("Each tool call must be an object.")

    function = call.get("function") or {}
    tool_name = (
        call.get("tool")
        or call.get("name")
        or call.get("tool_name")
        or function.get("name")
    )
    arguments = call.get("arguments", call.get("args"))

    if arguments is None and function:
        arguments = function.get("arguments", {})

    if arguments is None:
        arguments = {}

    if isinstance(arguments, str):
        arguments = json.loads(arguments or "{}")

    if not isinstance(arguments, dict):
        raise ValueError("Tool call arguments must be an object.")

    if not tool_name:
        raise ValueError("Tool call is missing a tool name.")

    return str(tool_name), arguments


@router.get("/config")
def get_providers():
    from ..core.database import engine

    with Session(engine) as session:
        providers = session.exec(select(AIProvider)).all()
        result = []
        for provider in providers:
            models = session.exec(
                select(AIModelConfig).where(AIModelConfig.provider_id == provider.id)
            ).all()
            provider_dict = (
                provider.model_dump()
                if hasattr(provider, "model_dump")
                else provider.dict()
            )
            provider_dict.pop("api_key", None)
            provider_dict["has_api_key"] = bool(provider.api_key)
            provider_dict["models"] = [
                model.model_dump() if hasattr(model, "model_dump") else model.dict()
                for model in models
            ]
            result.append(provider_dict)
        return result


@router.post("/config")
def save_provider(payload: ProviderDTO):
    from ..core.database import engine

    if payload.clear_api_key and payload.api_key:
        raise HTTPException(
            status_code=400, detail="Cannot replace and clear an API key together."
        )
    with Session(engine) as session:
        provider = (
            session.get(AIProvider, payload.id) if isinstance(payload.id, int) else None
        )
        if isinstance(payload.id, int) and provider is None:
            raise HTTPException(status_code=404, detail="AI provider not found.")
        if provider is not None and (
            payload.clear_api_key
            or (payload.api_key and payload.api_key != provider.api_key)
        ):
            _redact_stored_observability(session, _saved_secrets(session))
        if any(model.is_active for model in payload.models):
            all_models = session.exec(select(AIModelConfig)).all()
            for model in all_models:
                if model.is_active:
                    model.is_active = False
                    session.add(model)

        provider_data = (
            payload.model_dump(exclude={"id", "models", "api_key", "clear_api_key"})
            if hasattr(payload, "model_dump")
            else payload.dict(exclude={"id", "models", "api_key", "clear_api_key"})
        )

        if provider is None:
            provider = AIProvider(**provider_data)
        else:
            for key, value in provider_data.items():
                setattr(provider, key, value)
        if payload.clear_api_key:
            provider.api_key = ""
        elif payload.api_key:
            provider.api_key = payload.api_key

        session.add(provider)
        session.commit()
        session.refresh(provider)
        provider_id = provider.id
        assert provider_id is not None

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
                    model_db.provider_id = provider_id
                    session.add(model_db)
                    session.commit()
                    keep_model_ids.append(model_db.id)
                else:
                    new_model = AIModelConfig(**model_dict, provider_id=provider_id)
                    session.add(new_model)
                    session.commit()
                    session.refresh(new_model)
                    keep_model_ids.append(new_model.id)
            else:
                new_model = AIModelConfig(**model_dict, provider_id=provider_id)
                session.add(new_model)
                session.commit()
                session.refresh(new_model)
                keep_model_ids.append(new_model.id)

        existing_models = session.exec(
            select(AIModelConfig).where(AIModelConfig.provider_id == provider.id)
        ).all()
        for existing_model in existing_models:
            if existing_model.id not in keep_model_ids:
                session.delete(existing_model)
        session.commit()

        return {"status": "ok", "id": provider.id}


@router.delete("/config/{provider_id}")
def delete_provider(provider_id: int):
    from ..core.database import engine

    with Session(engine) as session:
        provider = session.get(AIProvider, provider_id)
        if provider:
            _redact_stored_observability(session, _saved_secrets(session))
            models = session.exec(
                select(AIModelConfig).where(AIModelConfig.provider_id == provider.id)
            ).all()
            for model in models:
                session.delete(model)
            session.delete(provider)
            session.commit()
        return {"status": "ok"}


@router.get("/history")
def get_histories():
    from ..core.database import engine

    with Session(engine) as session:
        convos = session.exec(
            select(AIConversation).order_by(col(AIConversation.updated_at).desc())
        ).all()
        return redact_secrets(
            [
                {"id": c.id, "title": c.title, "updated_at": c.updated_at}
                for c in convos
            ],
            _saved_secrets(session),
        )


@router.get("/history/{conv_id}")
def get_history(conv_id: int):
    from ..core.database import engine

    with Session(engine) as session:
        c = session.get(AIConversation, conv_id)
        if not c:
            raise HTTPException(status_code=404)
        return redact_secrets(
            {"id": c.id, "title": c.title, "messages": json.loads(c.messages_json)},
            _saved_secrets(session),
            redact_fields=False,
        )


@router.get("/history/{conv_id}/trace")
def get_history_trace(conv_id: int):
    from ..core.database import engine

    with Session(engine) as session:
        traces = session.exec(
            select(AITraceLog)
            .where(AITraceLog.conversation_id == conv_id)
            .order_by(col(AITraceLog.id).asc())
        ).all()
        return sanitize_trace_data(
            [
                {
                    "id": t.id,
                    "timestamp": t.timestamp.isoformat(),
                    "model_used": t.model_used,
                    "prompt_tokens": t.prompt_tokens,
                    "completion_tokens": t.completion_tokens,
                    "cost": t.cost,
                    "request_messages": json.loads(t.request_messages_json),
                    "response_message": json.loads(t.response_message_json),
                }
                for t in traces
            ],
            _saved_secrets(session),
        )


@router.post("/history")
def create_history(data: dict):
    from ..core.database import engine

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
    from ..core.database import engine

    with Session(engine) as session:
        c = session.get(AIConversation, conv_id)
        if not c:
            raise HTTPException(status_code=404)
        if "title" in data:
            c.title = data["title"]
        if "messages" in data:
            c.messages_json = json.dumps(data["messages"])
        c.updated_at = datetime.utcnow()
        session.add(c)
        session.commit()
        return {"status": "ok"}


@router.delete("/history/{conv_id}")
def delete_history(conv_id: int):
    from ..core.database import engine

    with Session(engine) as session:
        c = session.get(AIConversation, conv_id)
        if c:
            session.delete(c)

            traces = session.exec(
                select(AITraceLog).where(AITraceLog.conversation_id == conv_id)
            ).all()
            for t in traces:
                session.delete(t)

            session.commit()
        return {"status": "ok"}


@router.post("/manual/prompt-builder")
def build_manual_prompt(req: ManualPromptRequest):
    """Compile system rules, tools, and current state into a single prompt for external LLMs."""
    from ..services.prompts import build_system_prompt
    from .main import get_agent_context

    context = get_agent_context()
    printer_status = _resolve_printer_status(req.printer_info, context)
    safe_state = _sanitize_manual_canvas_state(copy.deepcopy(req.canvas_state))

    sys_prompt = build_system_prompt(context, printer_status)
    tools_str = json.dumps(TOOLS_SCHEMA, indent=2)
    state_str = json.dumps(safe_state, indent=2)

    is_empty = (
        len(req.canvas_state.get("items", [])) == 0
        and not str(req.canvas_state.get("htmlContent", "") or "").strip()
    )
    empty_note = (
        "- The canvas is currently empty. Create a new design from scratch satisfying the request."
        if is_empty
        else "- Respect the existing design whenever possible and make the smallest tool-based changes needed to satisfy the request."
    )

    final_prompt = f"""{sys_prompt}

YOUR AVAILABLE TOOLS:
{tools_str}

CURRENT CANVAS STATE:
{state_str}

USER REQUEST:
{req.intent.strip()}

IMPORTANT:
- The user may also attach or paste an image snapshot of the current canvas in the same conversation. If present, use that image as the visual source of truth for overlap, spacing, and alignment corrections.
{empty_note}

OUTPUT INSTRUCTIONS:
You must fulfill the user's request by calling the appropriate tools.
DO NOT output conversational text, explanations, or markdown outside of the JSON block.
You MUST output the JSON array inside a standard Markdown JSON code block (```json ... ```).

Example format:
[
  {{
    "tool": "apply_template",
    "arguments": {{ "template_id": "price_tag", "params": {{"currency_symbol": "$"}} }}
  }}
]
"""
    return {"prompt": final_prompt}


@router.post("/manual/execute")
def execute_manual_tools(req: ManualExecuteRequest):
    """Execute an array of tool calls against the provided canvas state."""
    canvas_state_copy = copy.deepcopy(req.canvas_state)
    results = []

    for index, call in enumerate(req.tool_calls):
        try:
            tool_name, arguments = _normalize_manual_tool_call(call)
            result = execute_tool(tool_name, arguments, canvas_state_copy)
            results.append(
                {
                    "index": index,
                    "tool": tool_name,
                    "status": "success",
                    "result": result,
                }
            )
        except Exception as e:
            results.append(
                {
                    "index": index,
                    "tool": call.get("tool") or call.get("name") or "unknown",
                    "status": "error",
                    "result": str(e),
                }
            )

    return {"canvas_state": canvas_state_copy, "execution_results": results}


@router.post("/chat")
def chat_with_agent(req: ChatRequest):
    from ..core.database import engine

    with Session(engine) as session:
        active_model = session.exec(
            select(AIModelConfig).where(col(AIModelConfig.is_active).is_(True))
        ).first()
        if not active_model:
            active_model = session.exec(select(AIModelConfig)).first()

        if not active_model:
            raise HTTPException(
                status_code=400,
                detail="No AI models configured. Please configure an AI Provider and Model in settings.",
            )

        active_provider = session.get(AIProvider, active_model.provider_id)
        if not active_provider:
            raise HTTPException(
                status_code=400,
                detail="The active AI model is linked to a missing provider. Please update your AI configuration.",
            )

        secrets = _saved_secrets(session)

    return _chat_with_provider(req, active_provider, active_model, secrets)


def _chat_with_provider(
    req: ChatRequest,
    active_provider: AIProvider,
    active_model: AIModelConfig,
    secrets: tuple[str, ...],
):
    credential_path = None
    try:
        kwargs = {
            "model": f"{active_provider.provider}/{active_model.model_name}"
            if active_provider.provider != "custom"
            else active_model.model_name,
            "tools": TOOLS_SCHEMA,
            "tool_choice": "auto",
        }

        if getattr(active_model, "reasoning_effort", ""):
            kwargs["reasoning_effort"] = active_model.reasoning_effort

        if not active_provider.use_env:
            if active_provider.provider == "vertex_ai":
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".json", mode="w"
                ) as f:
                    credential_path = f.name
                    f.write(active_provider.api_key)
                    kwargs["vertex_credentials"] = f.name
            else:
                kwargs["api_key"] = active_provider.api_key

            if active_provider.base_url:
                kwargs["api_base"] = active_provider.base_url

        if active_provider.provider == "vertex_ai" and getattr(
            active_provider, "vertex_region", ""
        ):
            kwargs["vertex_location"] = active_provider.vertex_region

        from .main import get_agent_context

        context = get_agent_context()

        from ..services.prompts import build_system_prompt

        printer_status = _resolve_printer_status(req.printer_info, context)

        sys_prompt = build_system_prompt(context, printer_status)

        is_empty = (
            len(req.canvas_state.get("items", [])) == 0
            and not str(req.canvas_state.get("htmlContent", "") or "").strip()
        )
        if is_empty:
            sys_prompt += "\n\nNOTE: The canvas is currently empty. Create a new design from scratch satisfying the request."

        messages = redact_secrets(
            [{"role": "system", "content": sys_prompt}] + req.messages,
            secrets,
            redact_fields=False,
        )

        # +++ NEW: Inject frontend base64 image into the last user message +++
        if (
            active_model.vision_capable
            and req.current_canvas_b64
            and messages
            and messages[-1].get("role") == "user"
        ):
            original_text = messages[-1].get("content", "")
            if isinstance(original_text, str):
                messages[-1]["content"] = [
                    {"type": "text", "text": original_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{req.current_canvas_b64}"
                        },
                    },
                ]

        canvas_state_copy = copy.deepcopy(req.canvas_state)

        MAX_ITERATIONS = 20
        iteration = 0
        new_messages = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0
        response: Any = None

        logger.info(
            "Starting LLM Agent loop using model: %s",
            redact_secrets(kwargs.get("model"), secrets),
        )

        while iteration < MAX_ITERATIONS:
            if iteration == MAX_ITERATIONS - 1:
                logger.warning(
                    "Agent reached maximum iterations (20). Forcing graceful termination."
                )
                messages.append(
                    {
                        "role": "system",
                        "content": "SYSTEM WARNING: You have reached the maximum number of tool execution turns allowed (20). You cannot use tools anymore in this session. Summarize what you have done so far, explain what is left, and ask the user if they want you to continue.",
                    }
                )
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)

            iteration += 1

            response = litellm.completion(messages=messages, **kwargs)

            call_prompt_tokens = 0
            call_completion_tokens = 0
            call_cost_val = 0.0

            usage = getattr(response, "usage", None)
            if usage:
                if isinstance(usage, dict):
                    call_prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                    call_completion_tokens = int(usage.get("completion_tokens", 0) or 0)
                else:
                    call_prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                    call_completion_tokens = int(
                        getattr(usage, "completion_tokens", 0) or 0
                    )

                total_prompt_tokens += call_prompt_tokens
                total_completion_tokens += call_completion_tokens

            try:
                call_cost_val = float(
                    litellm.completion_cost(completion_response=response) or 0.0
                )
                total_cost += call_cost_val
            except Exception:
                pass

            resp_msg = response.choices[0].message
            resp_dict = redact_secrets(
                serialize_msg(resp_msg), secrets, redact_fields=False
            )

            # Save the exact trace to the database for observability
            if req.conv_id is not None:
                from ..core.database import engine

                with Session(engine) as session:
                    # Sanitize to prevent massive DB bloat from base64 images
                    safe_messages = sanitize_trace_data(messages, secrets)
                    safe_response = sanitize_trace_data(resp_dict, secrets)

                    trace_log = AITraceLog(
                        conversation_id=req.conv_id,
                        model_used=redact_secrets(kwargs.get("model", ""), secrets),
                        prompt_tokens=call_prompt_tokens,
                        completion_tokens=call_completion_tokens,
                        cost=call_cost_val,
                        request_messages_json=json.dumps(safe_messages),
                        response_message_json=json.dumps(safe_response),
                    )
                    session.add(trace_log)
                    session.commit()

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

                    logger.info(
                        "➡️ Agent requested Tool Call: %s",
                        redact_secrets(fn_name, secrets),
                    )
                    logger.info(
                        "   Arguments: %s", sanitize_trace_data(args_str, secrets)
                    )

                    try:
                        fn_args = json.loads(args_str)
                        tool_result = execute_tool(fn_name, fn_args, canvas_state_copy)
                        logger.info(
                            "✅ Tool Result: %s",
                            sanitize_trace_data(tool_result, secrets),
                        )
                    except Exception as e:
                        tool_result = redact_secrets(
                            f"Error executing tool {fn_name}: {str(e)}", secrets
                        )
                        logger.error("❌ Tool Error: %s", tool_result)

                    tool_msg = {
                        "role": "tool",
                        "name": fn_name,
                        "tool_call_id": tc_id,
                        "content": str(
                            redact_secrets(tool_result, secrets, redact_fields=False)
                        ),
                    }
                    messages.append(tool_msg)
                    new_messages.append(tool_msg)

                # Check if the preview tool was called in this turn
                requested_preview = any(
                    (
                        tc.get("function", {}).get("name")
                        if isinstance(tc, dict)
                        else tc.function.name
                    )
                    == "request_visual_preview"
                    for tc in resp_msg.tool_calls
                )

                if requested_preview:
                    logger.info(
                        "🛑 Pausing backend agent loop to request visual preview from frontend."
                    )
                    canvas_state_copy.setdefault("__actions__", []).append(
                        {"action": "frontend_visual_preview"}
                    )
                    break
            else:
                logger.info("Agent finished turn. Total Cost so far: $%.4f", total_cost)
                break

        return {
            "new_messages": redact_secrets(new_messages, secrets, redact_fields=False),
            "canvas_state": redact_secrets(
                canvas_state_copy, secrets, redact_fields=False
            ),
            "usage": {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
                "cost": total_cost,
                "model_used": redact_secrets(
                    getattr(response, "model", kwargs.get("model"))
                    if response is not None
                    else kwargs.get("model"),
                    secrets,
                ),
            },
        }

    except Exception as exc:
        error_id = uuid4().hex
        safe_error = redact_secrets(str(exc), secrets)[:500]
        logger.error("AI chat failed [%s]: %s", error_id, safe_error)
        return {
            "error": safe_error,
            "error_id": error_id,
            "canvas_state": redact_secrets(
                req.canvas_state, secrets, redact_fields=False
            ),
        }
    finally:
        if credential_path is not None:
            Path(credential_path).unlink(missing_ok=True)
