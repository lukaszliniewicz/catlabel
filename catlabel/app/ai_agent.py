import json
import os
import tempfile
from datetime import datetime
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
    mac_address: str = None  # Capture printer address for context if available

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
3. Batches & Variables: If the user wants multiple varying labels (e.g., 5 different names, or sizes M3 to M8), DO NOT just tell them to use the CSV tool. Instead:
   a) Clear the canvas.
   b) Design ONE template label using `{{{{ variable_name }}}}` syntax.
   c) Immediately call `multiply_workspace_with_variables` providing the list of dictionaries for the batch. This visually generates the entire batch in the UI for them!
4. Printing & Saving: You can literally print the canvas or save it to the database for the user by using `trigger_ui_action`. ONLY do this if explicitly asked to "print it" or "save it".
5. Be highly proactive. If a user asks "Make a label for X", just execute the tools and say "I've created the layout for you."
"""

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
