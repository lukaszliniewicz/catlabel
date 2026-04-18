import os
import stat
import shutil
import subprocess
from pathlib import Path

# --- Configuration ---
DEST_APP_DIR = Path(r"C:\Users\llini\Downloads\TiMini-Print-fastapi")
DEST_MODULE_DIR = DEST_APP_DIR / "catlabel"
REPO_URL = "https://github.com/Dejniel/TiMini-Print.git"
TMP_CLONE_DIR = DEST_APP_DIR / "_upstream_tmp"

def remove_readonly(func, path, _):
    """Clear the readonly bit and reattempt the removal (fixes Windows .git folder deletion)."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def clone_repo():
    if TMP_CLONE_DIR.exists():
        print("[*] Cleaning up old temp directory...")
        shutil.rmtree(TMP_CLONE_DIR, onerror=remove_readonly)
    
    print(f"[*] Cloning {REPO_URL}...")
    subprocess.run(["git", "clone", REPO_URL, str(TMP_CLONE_DIR)], check=True)

def patch_file_imports(filepath: Path):
    """Replaces 'timiniprint' with 'catlabel' and severs broken upstream type-hints."""
    try:
        content = filepath.read_text(encoding="utf-8")
        original = content
        
        # 1. Global rename
        content = content.replace("timiniprint", "catlabel")
        
        # 2. Fix Upstream Type Hints that point to data models CatLabel handles via FastAPI/SQLModel
        if filepath.name == "v5g.py":
            content = content.replace(
                "from ...devices.profiles import PrinterProfile", 
                "from typing import Any as PrinterProfile"
            )
        elif filepath.name == "factory.py":
            content = content.replace(
                "from ...devices import PrinterDevice", 
                "from typing import Any as PrinterDevice"
            )
        elif filepath.name == "job.py":
            content = content.replace(
                "from ..devices.device import PrinterDevice",
                "from typing import Any as PrinterDevice"
            )

        if content != original:
            filepath.write_text(content, encoding="utf-8")
            print(f"      [Patched] {filepath.name}")
    except Exception as e:
        print(f"      [!] Failed to patch {filepath.name}: {e}")

def copy_and_patch():
    src_module = TMP_CLONE_DIR / "timiniprint"

    # 1. Copy & Patch printing/runtime
    src_runtime = src_module / "printing" / "runtime"
    dst_runtime = DEST_MODULE_DIR / "printing" / "runtime"
    print(f"\n[+] Copying {src_runtime.name} -> {dst_runtime.relative_to(DEST_APP_DIR)}")
    shutil.copytree(src_runtime, dst_runtime, dirs_exist_ok=True)
    for py_file in dst_runtime.rglob("*.py"):
        patch_file_imports(py_file)

    # 2. Copy & Patch protocol
    src_protocol = src_module / "protocol"
    dst_protocol = DEST_MODULE_DIR / "protocol"
    print(f"\n[+] Copying {src_protocol.name} -> {dst_protocol.relative_to(DEST_APP_DIR)}")
    shutil.copytree(src_protocol, dst_protocol, dirs_exist_ok=True)
    for py_file in dst_protocol.rglob("*.py"):
        patch_file_imports(py_file)

    # 3. Copy & Patch specific Bluetooth adapter files
    adapter_files = [
        "bleak_adapter_transport.py", 
        "bleak_adapter_endpoint_resolver.py", # <-- Added missing dependency!
        "bleak_adapter.py"
    ]
    src_adapters = src_module / "transport" / "bluetooth" / "adapters"
    dst_adapters = DEST_MODULE_DIR / "transport" / "bluetooth" / "adapters"
    dst_adapters.mkdir(parents=True, exist_ok=True)

    print(f"\n[+] Copying Bluetooth Adapters -> {dst_adapters.relative_to(DEST_APP_DIR)}")
    for file in adapter_files:
        src_file = src_adapters / file
        dst_file = dst_adapters / file
        shutil.copy2(src_file, dst_file)
        patch_file_imports(dst_file)

    # 4. GRAB THE MISSING RASTER FILE
    src_raster = src_module / "raster.py"
    dst_raster = DEST_MODULE_DIR / "raster.py"
    print(f"\n[+] Copying {src_raster.name} -> {dst_raster.relative_to(DEST_APP_DIR)}")
    shutil.copy2(src_raster, dst_raster)
    patch_file_imports(dst_raster)

    # 5. GRAB THE UPDATED RENDERER
    src_renderer = src_module / "rendering" / "renderer.py"
    dst_renderer = DEST_MODULE_DIR / "rendering" / "renderer.py"
    print(f"[+] Copying {src_renderer.name} -> {dst_renderer.relative_to(DEST_APP_DIR)}")
    shutil.copy2(src_renderer, dst_renderer)
    patch_file_imports(dst_renderer)

def clean_dead_code():
    print("\n[*] Purging dead legacy CLI code to fix FastAPI boot crashes...")
    
    # Nuke the old CLI printing files that crash when looking for the old 'devices' module
    dead_files = [
        DEST_MODULE_DIR / "printing" / "job.py",
        DEST_MODULE_DIR / "printing" / "settings.py",
        DEST_MODULE_DIR / "printing" / "builder.py"
    ]
    
    for f in dead_files:
        if f.exists():
            f.unlink()
            print(f"      [Deleted] {f.relative_to(DEST_APP_DIR)}")
            
    # Empty out the __init__.py so it stops eagerly importing the dead files
    init_file = DEST_MODULE_DIR / "printing" / "__init__.py"
    if init_file.exists():
        init_file.write_text("# Cleaned to allow FastAPI boot.\n", encoding="utf-8")
        print(f"      [Cleared] {init_file.relative_to(DEST_APP_DIR)}")

def cleanup():
    print("\n[*] Cleaning up temporary clone...")
    if TMP_CLONE_DIR.exists():
        shutil.rmtree(TMP_CLONE_DIR, onerror=remove_readonly)
    print("[*] Cleanup complete!")

if __name__ == "__main__":
    print("=== Upstream Engine Sync & Patch ===")
    
    if not DEST_MODULE_DIR.exists():
        print(f"\n[!] ERROR: Destination module directory not found: {DEST_MODULE_DIR}")
        exit(1)
        
    try:
        clone_repo()
        copy_and_patch()
        clean_dead_code()
    except Exception as e:
        print(f"\n[!] An error occurred: {e}")
    finally:
        cleanup()
        
    print("\n=== SUCCESS ===")
    print("The server will now boot properly!")