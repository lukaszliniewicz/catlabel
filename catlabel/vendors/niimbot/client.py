import asyncio
import enum
import struct
import logging
from typing import Dict, List, Optional, Tuple

from PIL import Image
from bleak import BleakClient, BleakError

from ..base import BasePrinterClient
from ...protocol.encoding import pack_line
from ...protocol.types import PixelFormat
from ...rendering.renderer import image_to_raster

# --- Configure robust logging for Niimbot ---
logger = logging.getLogger("NiimbotClient")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - [Niimbot] %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)


class RequestCodeEnum(enum.IntEnum):
    GET_INFO = 64
    GET_RFID = 26
    HEARTBEAT = 220
    SET_LABEL_TYPE = 35
    SET_LABEL_DENSITY = 33
    SET_PRINT_SPEED = 2
    START_PRINT = 1
    END_PRINT = 243
    START_PAGE_PRINT = 3
    END_PAGE_PRINT = 227
    ALLOW_PRINT_CLEAR = 32
    SET_DIMENSION = 19
    SET_QUANTITY = 21
    GET_PRINT_STATUS = 163


class InfoEnum(enum.IntEnum):
    DENSITY = 1
    PRINTSPEED = 2
    LABELTYPE = 3
    SOFTVERSION = 9
    BATTERY = 10
    DEVICESERIAL = 11
    HARDVERSION = 12


class NiimbotPacket:
    def __init__(self, type_, data):
        self.type = int(type_)
        self.data = bytes(data)

    @classmethod
    def from_bytes(cls, pkt: bytes) -> Optional["NiimbotPacket"]:
        if len(pkt) < 7 or pkt[:2] != b"\x55\x55" or pkt[-2:] != b"\xaa\xaa":
            return None
        type_ = pkt[2]
        length = pkt[3]
        if len(pkt) != length + 7:
            return None
        data = pkt[4 : 4 + length]

        checksum = type_ ^ length
        for value in data:
            checksum ^= value

        if checksum != pkt[-3]:
            logger.warning(f"Packet checksum mismatch! Expected {pkt[-3]}, got {checksum}")
            return None
        return cls(type_, data)

    def to_bytes(self) -> bytes:
        checksum = self.type ^ len(self.data)
        for value in self.data:
            checksum ^= value
        return bytes((0x55, 0x55, self.type, len(self.data), *self.data, checksum, 0xAA, 0xAA))


class NiimbotClient(BasePrinterClient):
    def __init__(self, device, hardware_info, printer_profile, settings):
        super().__init__(device, hardware_info, printer_profile, settings)
        self.client: Optional[BleakClient] = None
        self.notify_uuid: Optional[str] = None
        self.write_uuid: Optional[str] = None
        self._buffer = bytearray()
        self._events: Dict[int, Tuple[asyncio.Event, asyncio.AbstractEventLoop]] = {}
        self._responses: Dict[int, NiimbotPacket] = {}

    def _publish_response(self, req_code: int, packet: NiimbotPacket) -> None:
        self._responses[req_code] = packet
        event_data = self._events.get(req_code)
        if event_data is None:
            return
        event, _loop = event_data
        event.set()

    def _on_notify(self, sender, payload: bytearray) -> None:
        """Route raw Bleak notification packets back onto the waiting asyncio loop safely."""
        self._buffer.extend(payload)

        while True:
            start = self._buffer.find(b"\x55\x55")
            if start == -1:
                self._buffer.clear()
                return
            if start > 0:
                del self._buffer[:start]

            if len(self._buffer) < 7:
                return

            length = self._buffer[3]
            total_length = length + 7
            if len(self._buffer) < total_length:
                return

            if self._buffer[total_length - 2 : total_length] != b"\xaa\xaa":
                del self._buffer[:2]
                continue

            packet_bytes = bytes(self._buffer[:total_length])
            del self._buffer[:total_length]

            packet = NiimbotPacket.from_bytes(packet_bytes)
            if packet is None:
                continue

            matched_req_code = None
            if packet.type in self._events:
                matched_req_code = packet.type
            elif (packet.type - 1) in self._events:
                matched_req_code = packet.type - 1
            elif len(self._events) == 1 and packet.type not in (220, 163):
                matched_req_code = list(self._events.keys())[0]

            if matched_req_code is None:
                if packet.type not in (220, 163):
                    logger.debug(f"Unsolicited packet received: type={packet.type}, data={packet.data.hex()}")
                self._responses[packet.type] = packet
                continue

            event_data = self._events.get(matched_req_code)
            if event_data is None:
                self._responses[matched_req_code] = packet
                continue

            _event, loop = event_data
            if loop.is_closed():
                self._responses[matched_req_code] = packet
                continue

            loop.call_soon_threadsafe(self._publish_response, matched_req_code, packet)

    async def connect(self) -> bool:
        self._buffer.clear()
        self._events.clear()
        self._responses.clear()

        address = self.device.address
        if hasattr(self.device, "ble_endpoint") and self.device.ble_endpoint:
            address = self.device.ble_endpoint.address

        logger.info(f"Attempting native BLE connection to {address}...")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.client = BleakClient(address)
                await self.client.connect(timeout=10.0)
                
                self.notify_uuid = None
                self.write_uuid = None

                PREFERRED_COMBINED =["bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"]
                PREFERRED_WRITE =["49535343-8841-43f4-a8d4-ecbe34729bb3"]
                PREFERRED_NOTIFY =["49535343-1e4d-4bd9-ba61-23c647249616"]
                
                for service in self.client.services:
                    for char in service.characteristics:
                        uuid_str = str(char.uuid).lower()
                        if uuid_str in PREFERRED_COMBINED:
                            self.write_uuid = char.uuid
                            self.notify_uuid = char.uuid
                        elif uuid_str in PREFERRED_WRITE:
                            self.write_uuid = char.uuid
                        elif uuid_str in PREFERRED_NOTIFY:
                            self.notify_uuid = char.uuid

                if not self.write_uuid or not self.notify_uuid:
                    for service in self.client.services:
                        for char in service.characteristics:
                            uuid_str = str(char.uuid).lower()
                            props = char.properties
                            
                            # Skip the Air Patch which breaks normal communication
                            if "aca3-481c-91ec-d85e28a60318" in uuid_str:
                                continue
                                
                            if not self.write_uuid and ('write' in props or 'write-without-response' in props):
                                self.write_uuid = char.uuid
                            if not self.notify_uuid and ('notify' in props or 'indicate' in props):
                                self.notify_uuid = char.uuid

                if not self.write_uuid or not self.notify_uuid:
                    raise RuntimeError("Could not find valid TX/RX characteristics for Niimbot.")

                logger.debug(f"Bound to RX (notify): {self.notify_uuid} | TX (write): {self.write_uuid}")
                await self.client.start_notify(self.notify_uuid, self._on_notify)
                
                logger.info("Executing initial hardware handshake...")
                await self.send_command(RequestCodeEnum.HEARTBEAT, b"\x01", timeout=1.0)
                await self.send_command(RequestCodeEnum.GET_INFO, bytes([InfoEnum.DEVICESERIAL.value]), timeout=1.0)
                
                logger.info("Connected successfully.")
                return True
            except Exception as exc:
                logger.warning(f"Connection attempt {attempt + 1} failed: {exc}")
                self.last_error = exc
                if self.client and self.client.is_connected:
                    try:
                        await self.client.disconnect()
                    except:
                        pass
                self.client = None
                self.notify_uuid = None
                self.write_uuid = None
                await asyncio.sleep(1.5)
        
        logger.error("All connection attempts failed.")
        return False

    async def disconnect(self) -> None:
        try:
            logger.info("Disconnecting...")
            if self.client and self.client.is_connected:
                try:
                    await self.client.stop_notify(self.notify_uuid)
                except:
                    pass
                await self.client.disconnect()
        finally:
            self.client = None
            self.notify_uuid = None
            self.write_uuid = None
            self._buffer.clear()
            self._events.clear()
            self._responses.clear()

    async def send_command(self, req_code, data=b"", timeout=5.0):
        request_code = int(req_code)
        packet = NiimbotPacket(request_code, data)
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        self._responses.pop(request_code, None)
        self._events[request_code] = (event, loop)

        logger.debug(f"Sending cmd {request_code} (payload: {data.hex()})")
        try:
            await self.write_raw(packet.to_bytes())
            await asyncio.wait_for(event.wait(), timeout)
            res = self._responses.pop(request_code, None)
            logger.debug(f"Cmd {request_code} ACK'd. Response: {res.data.hex() if res else 'None'}")
            return res
        except asyncio.TimeoutError:
            logger.warning(f"Cmd {request_code} TIMED OUT after {timeout}s.")
            return None
        except Exception as e:
            logger.error(f"Cmd {request_code} Error: {e}")
            return None
        finally:
            current = self._events.get(request_code)
            if current is not None and current[0] is event:
                self._events.pop(request_code, None)

    async def write_raw(self, data: bytes) -> None:
        if not self.client or not self.client.is_connected:
            raise RuntimeError("BLE client disconnected during write.")
        
        # Stream out at max MTU
        for i in range(0, len(data), 128):
            chunk = data[i:i+128]
            try:
                await self.client.write_gatt_char(self.write_uuid, chunk, response=False)
            except BleakError:
                # Flow control fallback for overloaded buffer
                await self.client.write_gatt_char(self.write_uuid, chunk, response=True)

    def _prepare_print_image(self, image: Image.Image, print_width_px: int) -> Image.Image:
        working = image.copy()

        if working.width > print_width_px:
            ratio = print_width_px / float(working.width)
            new_height = max(1, int(working.height * ratio))
            working = working.resize((print_width_px, new_height), Image.Resampling.LANCZOS)

        if working.width < print_width_px:
            padded = Image.new("RGB", (print_width_px, working.height), "white")
            offset = (print_width_px - working.width) // 2
            padded.paste(working, (offset, 0))
            working = padded

        return working.convert("RGB")

    async def _wait_for_end_page_ack(self, timeout: float = 15.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        logger.debug("Waiting for END_PAGE_PRINT acknowledgment...")
        while True:
            packet = await self.send_command(RequestCodeEnum.END_PAGE_PRINT, b"\x01", timeout=1.0)
            if packet and len(packet.data) > 0:
                if packet.data[0] == 1:
                    logger.debug("END_PAGE_PRINT acknowledged.")
                    return
                else:
                    logger.debug(f"Printer busy ({packet.data.hex()}), retrying END_PAGE_PRINT...")
            
            if asyncio.get_running_loop().time() >= deadline:
                logger.warning("Timed out waiting for END_PAGE_PRINT ack. Proceeding to prevent lockup.")
                return
            await asyncio.sleep(0.2)

    async def print_images(self, images: List[Image.Image], split_mode: bool = False, dither: bool = True) -> None:
        logger.info(f"Starting batch print job for {len(images)} image(s) using independent jobs...")
        
        default_density = int(self.hardware_info.get("default_energy", 3) or 3)
        max_allowed = max(1, int(self.hardware_info.get("max_density", 5) or 5))
        raw_density = (
            self.printer_profile.energy
            if self.printer_profile and self.printer_profile.energy not in (None, 0)
            else default_density
        )
        density = max(1, min(int(raw_density), max_allowed))
        
        print_width_px = max(1, int(self.hardware_info.get("width_px", 120) or 120))
        media_type_str = self.hardware_info.get("media_type", "pre-cut")
        label_type = 2 if media_type_str == "continuous" else 1

        try:
            for i, image in enumerate(images):
                logger.info(f"--- Printing label {i + 1} of {len(images)} ---")
                
                # FORCE STATE CLEAR before each label to avoid "Job Full" (Error 06) firmware issues
                await self.send_command(RequestCodeEnum.END_PRINT, b"\x01", timeout=1.0)
                await self.send_command(RequestCodeEnum.ALLOW_PRINT_CLEAR, b"\x01", timeout=1.0)

                # Session Setup
                await self.send_command(RequestCodeEnum.SET_LABEL_DENSITY, bytes([density]), timeout=1.0)
                await self.send_command(RequestCodeEnum.SET_LABEL_TYPE, bytes([label_type]), timeout=1.0)
                
                # Start 1-page Job explicitly
                start_pkt = await self.send_command(RequestCodeEnum.START_PRINT, b"\x01", timeout=2.0)
                if not start_pkt or not start_pkt.data or start_pkt.data[0] == 0:
                    logger.warning("Printer returned 0x00 for START_PRINT. State might be dirty. Forcing anyway...")

                prepared = self._prepare_print_image(image, print_width_px)
                raster = image_to_raster(prepared, PixelFormat.BW1, dither=dither)
                packed_bytes = pack_line(raster.pixels, lsb_first=False)
                width_bytes = (raster.width + 7) // 8

                page_pkt = await self.send_command(RequestCodeEnum.START_PAGE_PRINT, b"\x01", timeout=2.0)
                if not page_pkt or not page_pkt.data or page_pkt.data[0] == 0:
                    logger.warning(f"Printer rejected START_PAGE_PRINT. Forcing transmission...")

                await self.send_command(
                    RequestCodeEnum.SET_DIMENSION,
                    struct.pack(">HH", raster.height, raster.width),
                    timeout=2.0
                )
                await self.send_command(RequestCodeEnum.SET_QUANTITY, struct.pack(">H", 1), timeout=2.0)

                logger.debug(f"Streaming {raster.height} rows of raster data...")
                for y in range(raster.height):
                    line_data = packed_bytes[y * width_bytes : (y + 1) * width_bytes]
                    header = struct.pack(">HBBBB", y, 0, 0, 0, 1)
                    packet = NiimbotPacket(0x85, header + line_data)
                    await self.write_raw(packet.to_bytes())
                    
                    if y % 32 == 0:
                        await asyncio.sleep(0.01)

                logger.debug("Row streaming complete. Waiting for ACK...")
                await self._wait_for_end_page_ack(timeout=15.0)

                logger.info(f"Tearing down print session for label {i + 1}...")
                await self.send_command(RequestCodeEnum.END_PRINT, b"\x01", timeout=3.0)

                if i < len(images) - 1:
                    logger.debug("Waiting for physical printer to finish feeding paper before next label...")
                    # This physically acts as a throttle between single-page jobs so the hardware
                    # doesn't immediately abort the second job with "06" while the print-head is still engaged.
                    await asyncio.sleep(2.5)

        except Exception as e:
            logger.error(f"Print job FAILED: {e}")
            raise RuntimeError(f"Print failed: {e}")
        finally:
            logger.info("Cleaning up printer state...")
            try:
                await self.send_command(RequestCodeEnum.END_PRINT, b"\x01", timeout=1.0)
            except:
                pass
            await asyncio.sleep(0.5)
