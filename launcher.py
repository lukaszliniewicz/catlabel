from __future__ import annotations

import os
import platform
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

try:
    from dulwich import porcelain
except ImportError:
    porcelain = None


REPO_URL = "https://github.com/lukaszliniewicz/catlabel.git"
TARGET_DIR_NAME = "catlabel"


def launcher_directory() -> Path:
    """Return the folder containing the script or frozen launcher executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def pause_on_error() -> None:
    with suppress(EOFError):
        input("Press Enter to exit...")


def clone_repo(target_dir: Path) -> bool:
    print(f"[*] Cloning CatLabel repository from {REPO_URL}...")
    print("[*] Please wait, this might take a moment...")
    try:
        if porcelain is None:
            raise RuntimeError("Dulwich is unavailable")
        repo = porcelain.clone(REPO_URL, str(target_dir))
        repo.close()
    except Exception as exc:
        print(f"[!] Error cloning repository: {exc}")
        return False
    print("[*] Clone complete!")
    return True


def update_repo(target_dir: Path) -> bool:
    print(f"[*] Checking for updates in {target_dir.name}...")
    try:
        if porcelain is None:
            raise RuntimeError("Dulwich is unavailable")
        with porcelain.open_repo(str(target_dir)) as repo:
            current_commit = repo.head()
            porcelain.pull(repo, REPO_URL, ff_only=True)
            new_commit = repo.head()
    except Exception as exc:
        print(f"[!] Error updating repository: {exc}. Continuing with the local copy.")
        return False

    if current_commit != new_commit:
        print(
            "[*] Updates pulled successfully! Marking the environment for synchronization."
        )
        (target_dir / ".update_needed").write_text("1", encoding="ascii")
    else:
        print("[*] CatLabel is up to date.")
    return True


def environment_exists(target_dir: Path) -> bool:
    environments_dir = target_dir / ".pixi" / "envs"
    return any(
        (environments_dir / name / "python.exe").is_file()
        for name in ("default", "headless")
    )


def run_app(target_dir: Path) -> int:
    print("[*] Handing over to the CatLabel Bootstrapper...\n")
    system = platform.system().lower()

    if "windows" in system:
        script = target_dir / "run.bat"
        # cmd.exe applies special quote stripping after /c. Running the script by
        # name from its working directory is reliable even when that path has spaces.
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", script.name]
    else:
        script = target_dir / "run.sh"
        command = [str(script)]
        if script.exists():
            script.chmod(0o755)

    if not script.is_file():
        print(
            f"[!] Critical error: {script.name} was not found in the cloned repository."
        )
        pause_on_error()
        return 1

    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(command, cwd=str(target_dir))
        return_code = process.wait()
    except KeyboardInterrupt:
        print("\n[*] Interrupted by user. Shutting down...")
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        return 130
    except Exception as exc:
        print(f"[!] Error running the application: {exc}")
        pause_on_error()
        return 1

    if return_code != 0:
        print(f"[!] CatLabel Bootstrapper exited with code {return_code}.")
    return return_code


def main() -> int:
    print("=========================================")
    print("          CatLabel Studio Launcher       ")
    print("=========================================\n")

    if porcelain is None:
        print("Dulwich is required to run this script from source.")
        print("Install it via: python -m pip install -r launcher-requirements.txt")
        pause_on_error()
        return 1

    target_dir = launcher_directory() / TARGET_DIR_NAME
    if not target_dir.exists():
        print(f"[*] Target directory '{TARGET_DIR_NAME}' not found.")
        print("[*] Initializing new installation...")
        if not clone_repo(target_dir):
            pause_on_error()
            return 1
    else:
        if not (target_dir / ".git").is_dir():
            print(
                f"[!] The directory '{target_dir}' exists but is not a valid repository."
            )
            print("[!] Please delete or rename the folder and try again.")
            pause_on_error()
            return 1

        update_repo(target_dir)

        if environment_exists(target_dir):
            print("[*] Existing Pixi setup detected. Launching CatLabel...")
        else:
            print("[*] Repository found, but the Pixi environment is missing.")
            print("[*] Setup will begin downloading dependencies now...")

    return run_app(target_dir)


if __name__ == "__main__":
    raise SystemExit(main())
