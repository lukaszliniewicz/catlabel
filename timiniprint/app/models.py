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

class Template(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    canvas_state_json: str
