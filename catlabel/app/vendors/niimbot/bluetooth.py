import asyncio
import logging
from bleak import BleakClient, BleakScanner

from .exception import BLEException

logger = logging.getLogger(__name__)


async def find_device(device_name_prefix=None):
    devices = await BleakScanner.discover()
    for device in devices:
        if device.name and device.name.lower().startswith(device_name_prefix.lower()):
            return device
    raise BLEException(f"Failed to find device {device_name_prefix}")


async def scan_devices(device_name=None):
    print("Scanning for devices...")
    devices = await BleakScanner.discover()
    for device in devices:
        if device_name:
            if device.name and device_name.lower() in device.name.lower():
                print(f"Found device: {device.name} at {device.address}")
                return device
        else:
            print(f"Found device: {device.name} at {device.address}")
    return None


class BLETransport:
    def __init__(self, address=None):
        self.address = address
        self.client = None

    async def __aenter__(self):
        # Automatically connect if address is provided during initialization
        if self.address:
            self.client = BleakClient(self.address)
            if await self.client.connect():
                logger.info(f"Connected to {self.address}")
                return self
            else:
                raise BLEException(f"Failed to connect to the BLE device at {self.address}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.disconnect()
            logger.info("Disconnected.")

    async def connect(self, address):
        if self.client is None:
            # Resolve the actual BLEDevice to prevent BleakDeviceNotFoundError on Win/Mac
            device = await BleakScanner.find_device_by_address(address, timeout=5.0)
            if not device:
                # Fallback to discover
                devices = await BleakScanner.discover(timeout=5.0)
                device = next((d for d in devices if d.address.upper() == address.upper()), None)
            self.client = BleakClient(device or address)
            
        try:
            if not self.client.is_connected:
                await self.client.connect()
        except Exception as e:
            logger.error(f"Bleak connection failed: {e}")
            
        return self.client.is_connected

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()

    async def write(self, data, char_uuid):
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(char_uuid, data)
        else:
            raise BLEException("BLE client is not connected.")

    async def start_notification(self, char_uuid, handler):
        if self.client and self.client.is_connected:
            await self.client.start_notify(char_uuid, handler)
        else:
            raise BLEException("BLE client is not connected.")

    async def stop_notification(self, char_uuid):
        if self.client and self.client.is_connected:
            await self.client.stop_notify(char_uuid)
        else:
            raise BLEException("BLE client is not connected.")
