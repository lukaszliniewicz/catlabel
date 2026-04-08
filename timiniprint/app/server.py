import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from sqlmodel import SQLModel, create_engine, Session, select

from .models import PrinterProfile, Font, Template
from ..devices import DeviceResolver, PrinterModelRegistry
from ..transport.bluetooth import SppBackend
from .. import reporting

sqlite_file_name = "timiniprint.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(title="TiMini Print Server", lifespan=lifespan)

@app.get("/api/printers/scan")
async def scan_printers():
    registry = PrinterModelRegistry.load()
    resolver = DeviceResolver(registry)
    devices, failures = await resolver.scan_printer_devices_with_failures(
        include_classic=True,
        include_ble=True,
    )
    
    results = []
    for device in devices:
        results.append({
            "name": device.name,
            "address": device.address,
            "display_address": device.display_address,
            "transport": device.transport.value,
            "paired": device.paired,
        })
    return {"devices": results, "failures": [str(f.error) for f in failures]}
