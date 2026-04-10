import json
import os
import tempfile
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select
import litellm

# Set up dedicated logging for deep visibility into the Agent loop
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] AI_AGENT: %(message)s")

from .models import AIConfig, AIConversation
from .ai_tools import TOOLS_SCHEMA, execute_tool

router = APIRouter(prefix="/api/ai", tags=["AI Agent"])

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    canvas_state: Dict[str, Any]
    mac_address: Optional[str] = None

def serialize_msg(msg) -> Dict[str, Any]:
    """
    Safely handle Pydantic v1/v2 or dicts from LiteLLM and sanitize them.
    Ensures no internal Litellm metadata is leaked back into the message history.
    """
    if hasattr(msg, "model_dump"):
        d = msg.model_dump(exclude_none=True)
    elif hasattr(msg, "dict"):
        d = msg.dict(exclude_none=True)
    else:
        d = dict(msg)
        
    allowed_keys = {"role", "content", "name", "tool_calls", "tool_call_id"}
    clean_d = {k: v for k, v in d.items() if k in allowed_keys}
    
    # Provider APIs require 'content' key even if null when assistant calls a tool
    if clean_d.get("role") == "assistant" and "content" not in clean_d:
        clean_d["content"] = None
        
    return clean_d

@router.get("/config")
def get_config():
    from .server import engine
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
    from .server import engine
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
        config = session.get(AIConfig, 1) or AIConfig()

    kwargs = {
        "model": f"{config.provider}/{config.model_name}" if config.provider != "custom" else config.model_name,
        "tools": TOOLS_SCHEMA,
        "tool_choice": "auto"
    }

    if not config.use_env:
        if config.provider == "vertex_ai":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w") as f:
                f.write(config.api_key)
                kwargs["vertex_credentials"] = f.name
        else:
            kwargs["api_key"] = config.api_key
            
        if config.base_url:
            kwargs["api_base"] = config.base_url

    context = get_agent_context()
    
    sys_prompt = f"""You are an expert Label Design AI Assistant for CatLabel.
Your job is to act as a layout engineer, designing thermal printer labels and executing physical UI actions on behalf of the user.

CONTEXT:
- Today's Date: {datetime.now().strftime('%A, %B %d, %Y')}
- Hardware Print Width: {context['engine_rules']['hardware_width_px']} pixels ({context['engine_rules']['hardware_width_mm']}mm)
- 1 mm = 8 pixels. ALWAYS use pixels for canvas dimensions and positions.
- Default Font: {context['global_default_font']}

TOOL USAGE RULES:
1. Dates & Text: Use `add_text_element` for general layout. You already know today's date from the context above.
2. Shipping Labels: DO NOT build them manually element by element. ALWAYS use `create_shipping_label` for perfect formatting.
3. Batches & Variables: If the user wants multiple varying labels, clear the canvas, design ONE template using `{{{{ variable_name }}}}` syntax, then call `multiply_workspace_with_variables` providing the list of dictionaries for the batch.
4. Printing & Saving: You can print the canvas or save it to the database for the user by using `trigger_ui_action`. ONLY do this if explicitly asked to "print it" or "save it".
5. Be highly proactive. If a user asks "Make a label for X", execute the tools and say "I've created the layout for you."
"""

    messages =[{"role": "system", "content": sys_prompt}] + req.messages
    canvas_state_copy = dict(req.canvas_state)

    try:
        logger.info(f"Processing incoming chat request with {len(req.messages)} history messages.")
        
        MAX_ITERATIONS = 20 # Safety ceiling to prevent infinite loops
        iteration = 0
        new_messages =[]
        
        # AGENT LOOP: Keep calling LLM as long as it returns tools to execute
        while iteration < MAX_ITERATIONS:
            iteration += 1
            logger.info(f"LLM Call Iteration {iteration}...")
            
            response = litellm.completion(messages=messages, **kwargs)
            resp_msg = response.choices[0].message
            resp_dict = serialize_msg(resp_msg)
            
            messages.append(resp_dict)
            new_messages.append(resp_dict)
            
            if hasattr(resp_msg, 'tool_calls') and resp_msg.tool_calls:
                logger.info(f"LLM issued {len(resp_msg.tool_calls)} tool call(s).")
                
                for tool_call in resp_msg.tool_calls:
                    # Litellm sometimes maps tool_calls to dicts, sometimes objects depending on model
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
                        logger.info(f"Executing tool: {fn_name} with args: {fn_args}")
                        tool_result = execute_tool(fn_name, fn_args, canvas_state_copy)
                        logger.info(f"Tool {fn_name} completed successfully.")
                    except json.JSONDecodeError as e:
                        # Auto-correction: If model truncated JSON, catch it and feed the error back
                        logger.error(f"JSON decode error in tool {fn_name}. Received: {args_str}")
                        tool_result = f"Error: Invalid JSON arguments returned by model: {str(e)}"
                    except Exception as e:
                        logger.error(f"Error executing tool {fn_name}: {str(e)}")
                        tool_result = f"Error executing tool {fn_name}: {str(e)}"
                    
                    tool_msg = {
                        "role": "tool",
                        "name": fn_name,
                        "tool_call_id": tc_id,
                        "content": str(tool_result)
                    }
                    messages.append(tool_msg)
                    new_messages.append(tool_msg)
                    
                # Tools executed. Loop continues back to `litellm.completion()` to let the model evaluate the results.
            else:
                logger.info("LLM responded with a final conversational reply.")
                break # Exit the agent loop
                
        if iteration == MAX_ITERATIONS:
            logger.warning("Reached maximum tool execution iterations.")
            msg = {
                "role": "assistant",
                "content": "I've reached my safety limit for consecutive tool executions. Please review the layout so far and let me know how to proceed."
            }
            messages.append(msg)
            new_messages.append(msg)

        return {
            "new_messages": new_messages,
            "canvas_state": canvas_state_copy
        }
        
    except Exception as e:
        logger.exception("Catastrophic error during Litellm chat generation.")
        return {"error": str(e), "canvas_state": req.canvas_state}
