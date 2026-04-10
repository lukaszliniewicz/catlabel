import json
import os
import tempfile
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Dict, Any
from sqlmodel import Session, select
import litellm

from .models import AIConfig
from .server import engine, get_agent_context
from .ai_tools import TOOLS_SCHEMA, execute_tool

router = APIRouter(prefix="/api/ai", tags=["AI Agent"])

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    canvas_state: Dict[str, Any]

@router.get("/config")
def get_config():
    with Session(engine) as session:
        config = session.get(AIConfig, 1)
        if not config:
            config = AIConfig()
            session.add(config)
            session.commit()
            session.refresh(config)
        return config

@router.post("/config")
def update_config(new_config: AIConfig):
    with Session(engine) as session:
        config = session.get(AIConfig, 1)
        if not config:
            config = AIConfig()
        config.provider = new_config.provider
        config.model_name = new_config.model_name
        config.api_key = new_config.api_key
        config.base_url = new_config.base_url
        config.use_env = new_config.use_env
        session.add(config)
        session.commit()
        return config

@router.post("/chat")
def chat_with_agent(req: ChatRequest):
    with Session(engine) as session:
        config = session.get(AIConfig, 1) or AIConfig()

    # Setup Litellm kwargs based on config
    kwargs = {
        "model": f"{config.provider}/{config.model_name}" if config.provider != "custom" else config.model_name,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto"
    }

    if not config.use_env:
        if config.provider == "vertex_ai":
            # Vertex AI typically requires a JSON key file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as f:
                f.write(config.api_key)
                kwargs["vertex_credentials"] = f.name
        else:
            kwargs["api_key"] = config.api_key
            
        if config.base_url:
            kwargs["api_base"] = config.base_url

    # Construct System Prompt with Canvas Context
    context = get_agent_context()
    sys_prompt = f"""You are a helpful Label Design AI Assistant for TiMini Print.
    Your job is to help the user design thermal printer labels by reasoning about their request and using your tools to manipulate the canvas.
    CURRENT CANVAS STATE: {json.dumps(req.canvas_state)}
    HARDWARE/CONTEXT: {json.dumps(context)}
    NOTE: Respond conversationally, but automatically use tools to apply changes when the user asks you to create/modify something."""

    messages = [{"role": "system", "content": sys_prompt}] + req.messages
    canvas_state_copy = dict(req.canvas_state)

    try:
        response = litellm.completion(messages=messages, **kwargs)
        resp_msg = response.choices[0].message
        
        # Handle Tool Calling Loop
        if resp_msg.tool_calls:
            messages.append(resp_msg.model_dump()) # Add assistant's tool call request to history
            for tool_call in resp_msg.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                tool_result = execute_tool(fn_name, fn_args, canvas_state_copy)
                
                messages.append({
                    "role": "tool",
                    "name": fn_name,
                    "tool_call_id": tool_call.id,
                    "content": tool_result
                })
            
            # Second call to get the final conversational response after tools executed
            second_response = litellm.completion(messages=messages, **kwargs)
            final_text = second_response.choices[0].message.content
        else:
            final_text = resp_msg.content

        return {
            "message": final_text,
            "canvas_state": canvas_state_copy
        }
    except Exception as e:
        return {"error": str(e), "canvas_state": req.canvas_state}
