import asyncio
import base64
from io import BytesIO
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException

from pydantic import BaseModel
from sqlmodel import Session, select

from ..core.database import engine
from ..core.models import PrinterProfile, Settings
from ..transport.bluetooth import SppBackend
from ..rendering.template import render_via_browser

router = APIRouter(tags=["Print"])

class PrintRequest(BaseModel):
    mac_address: str
    variables: Dict[str, str] = {}

class DirectPrintRequest(BaseModel):
    mac_address: str
    canvas_state: Dict[str, Any]
    variables: Dict[str, str] = {}
    dither: bool = True

class BatchPrintRequest(BaseModel):
    mac_address: str
    canvas_state: Dict[str, Any]
    copies: int = 1
    variables_list: List[Dict[str, str]] = []
    variables_matrix: Optional[Dict[str, List[str]]] = None
    dither: bool = True

class ImagePrintRequest(BaseModel):
    mac_address: str
    images: List[str]
    split_mode: bool = False
    is_rotated: bool = False
    dither: bool = True

class PrinterProfileUpdate(BaseModel):
    speed: Optional[int] = None
    energy: Optional[int] = None
    feed_lines: Optional[int] = None

# SppBackend uses a cache for scanned devices
_scanned_devices_cache: List[Any] = []

def _recognized_scanned_devices(devices: List[Any]) -> List[Any]:
    from ..vendors import VendorRegistry

    recognized = []
    for device in devices:
        name = device.name or "Unknown Printer"
        hardware_info = VendorRegistry.identify_device(name, device, device.address)

        if hardware_info.get("vendor") == "generic" and hardware_info.get("model_id") == "generic":
            continue

        transport = getattr(device, "transport", None)
        transport_value = transport.value if hasattr(transport, "value") else str(transport or "").lower()
        if hardware_info.get("vendor") in {"niimbot", "phomemo"} and transport_value != "ble":
            continue

        recognized.append(device)

    return recognized

def _scan_result_payload(device: Any) -> Dict[str, Any]:
    from ..vendors import VendorRegistry

    name = device.name or "Unknown Printer"
    hardware_info = VendorRegistry.identify_device(name, device, device.address)
    transport = getattr(device, "transport", None)
    transport_value = transport.value if hasattr(transport, "value") else str(transport or "").lower()

    return {
        **hardware_info,
        "name": name,
        "address": device.address,
        "display_address": getattr(device, "display_address", device.address),
        "paired": device.paired,
        "transport": transport_value or None,
    }

@router.get("/api/printers/supported_models")
def get_supported_models():
    from ..vendors import VendorRegistry
    return {"models": VendorRegistry.get_all_models()}

@router.get("/api/printers/model/{name}")
def get_printer_model_info(name: str):
    from ..vendors import VendorRegistry
    return VendorRegistry.identify_device(name)

@router.get("/api/printers/scan")
async def scan_printers():
    global _scanned_devices_cache
    devices, failures = await SppBackend.scan_with_failures(
        include_classic=True,
        include_ble=True,
    )
    _scanned_devices_cache = _recognized_scanned_devices(devices)

    results = [_scan_result_payload(device) for device in _scanned_devices_cache]
    return {"devices": results, "failures": [str(f.error) for f in failures]}

@router.get("/api/printers/{mac_address}/profile")
def get_printer_profile(mac_address: str):
    with Session(engine) as session:
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        if not profile:
            profile = PrinterProfile(mac_address=mac_address)
            session.add(profile)
            session.commit()
            session.refresh(profile)
        return profile

@router.put("/api/printers/{mac_address}/profile")
def update_printer_profile(mac_address: str, update: PrinterProfileUpdate):
    with Session(engine) as session:
        profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()
        if not profile:
            profile = PrinterProfile(mac_address=mac_address)

        if update.speed is not None:
            profile.speed = update.speed
        if update.energy is not None:
            profile.energy = update.energy
        if update.feed_lines is not None:
            profile.feed_lines = update.feed_lines

        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile

async def execute_print_jobs(mac_address: str, images: List[Any], split_mode: bool = False, dither: bool = True):
    global _scanned_devices_cache

    with Session(engine) as session:
        settings = session.get(Settings, 1) or Settings()
        printer_profile = session.exec(
            select(PrinterProfile).where(PrinterProfile.mac_address == mac_address)
        ).first()

    target_device = next((d for d in _scanned_devices_cache if d.address == mac_address), None)

    if not target_device:
        devices, _ = await SppBackend.scan_with_failures(
            include_classic=True,
            include_ble=True,
        )
        _scanned_devices_cache = _recognized_scanned_devices(devices)
        target_device = next((d for d in _scanned_devices_cache if d.address == mac_address), None)

    if not target_device:
        raise HTTPException(status_code=404, detail=f"Printer {mac_address} not found. Is it turned on?")

    from ..vendors import VendorRegistry
    hardware_info = VendorRegistry.identify_device(
        getattr(target_device, "name", ""),
        target_device,
        target_device.address,
    )

    manifest = VendorRegistry.get_manifest(hardware_info["vendor"])
    client = manifest.get_client(target_device, hardware_info, printer_profile, settings)

    connected = await client.connect()
    if not connected:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to connect to printer via {hardware_info['vendor']} engine.",
        )

    try:
        await client.print_images(images, split_mode, dither=dither)
    finally:
        await client.disconnect()

async def execute_print_job(mac_address: str, img: Any, split_mode: bool = False, dither: bool = True):
    await execute_print_jobs(mac_address, [img], split_mode, dither=dither)


@router.post("/api/print/direct")
async def print_direct(request: DirectPrintRequest):
    split_mode = request.canvas_state.get("splitMode", False)
    images = await asyncio.to_thread(
        render_via_browser,
        request.canvas_state,
        [request.variables or {}],
        1,
    )
    await execute_print_jobs(request.mac_address, images, split_mode, dither=request.dither)

    return {
        "status": "success",
        "message": f"Direct print successful to {request.mac_address}",
        "mac_address": request.mac_address
    }

@router.post("/api/print/batch")
async def print_batch(request: BatchPrintRequest):
    split_mode = request.canvas_state.get("splitMode", False)

    variables_collection = []
    if request.variables_list:
        variables_collection.extend(request.variables_list)

    if request.variables_matrix:
        import itertools
        keys = list(request.variables_matrix.keys())
        values = list(request.variables_matrix.values())
        for combination in itertools.product(*values):
            variables_collection.append(dict(zip(keys, combination)))

    if not variables_collection:
        variables_collection = [{}]

    images = await asyncio.to_thread(
        render_via_browser,
        request.canvas_state,
        variables_collection,
        request.copies,
    )

    await execute_print_jobs(request.mac_address, images, split_mode, dither=request.dither)
    return {"status": "success", "printed": len(images)}

@router.post("/api/print/images")
async def print_images_direct(request: ImagePrintRequest):
    from PIL import Image

    if not request.images:
        return {"status": "success", "printed": 0}

    def _process_images(images_b64, is_rotated):
        pil_images = []
        for b64_image in images_b64:
            image_data = b64_image.split(",", 1)[1] if "," in b64_image else b64_image
            decoded = base64.b64decode(image_data)
            with Image.open(BytesIO(decoded)) as image:
                rendered = image.convert("RGB")
                if is_rotated:
                    rendered = rendered.rotate(90, expand=True)
                pil_images.append(rendered)
        return pil_images

    try:
        pil_images = await asyncio.to_thread(_process_images, request.images, request.is_rotated)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid image payload supplied.") from exc

    await execute_print_jobs(request.mac_address, pil_images, request.split_mode, dither=request.dither)
    return {"status": "success", "printed": len(pil_images)}
