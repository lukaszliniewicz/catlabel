from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

class PrinterProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    mac_address: str = Field(index=True, unique=True)
    name: Optional[str] = None
    transport: str = "BLE"
    default_darkness: int = 3

class Font(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    file_path: str

class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    canvas_state_json: str

class Settings(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)
    paper_width_mm: float = 58.0
    print_width_mm: float = 48.0
    default_dpi: int = 203
    speed: int = 0
    energy: int = 0
    feed_lines: int = 100
    default_font: str = "Roboto.ttf"

class Address(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    alias: str
    name: str
    street: str
    zip: str
    city: str
    country: str

class AIConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)
    provider: str = "openai" # 'openai', 'gemini', 'vertex_ai', 'custom'
    model_name: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    use_env: bool = False

class AIConversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = "New Conversation"
    messages_json: str = "[]"
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class AIAgentProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = "Default Profile"
    provider: str = "openai" # 'openai', 'gemini', 'vertex_ai', 'custom'
    model_name: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    use_env: bool = False
    vision_capable: bool = False
    is_active: bool = False
