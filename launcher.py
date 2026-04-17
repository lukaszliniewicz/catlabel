import os
import sys
import subprocess
import platform

try:
    from dulwich import porcelain
except ImportError:
    print("Dulwich is required to run this script from source.")
    print("Install it via: pip install dulwich urllib3")
    sys.exit(1)

REPO_URL = "https://github.com/lukaszliniewicz/catlabel.git"
TARGET_DIR = "catlabel"

def clone_repo():
    print(f"[*] Cloning CatLabel repository from {REPO_URL}...")
    print("[*] Please wait, this might take a moment...")
    try:
        porcelain.clone(REPO_URL, TARGET_DIR)
        print("[*] Clone complete!")
    except Exception as e:
        print(f"[!] Error cloning repository: {e}")
        input("Press Enter to exit...")
        sys.exit(1)

def update_repo():
    print(f"[*] Checking for updates in {TARGET_DIR}...")
    try:
        repo = porcelain.open_repo(TARGET_DIR)
        # Getting current commit
        current_commit = repo.head()
        porcelain.pull(repo, REPO_URL)
        new_commit = repo.head()
        if current_commit != new_commit:
            print("[*] Updates pulled successfully! Marking for rebuild.")
            with open(os.path.join(TARGET_DIR, ".update_needed"), "w") as f:
                f.write("1")
        else:
            print("[*] CatLabel is up to date.")
    except Exception as e:
        print(f"[!] Error updating repository: {e}. Skipping update.")

def run_app():
    print("[*] Handing over to the CatLabel Bootstrapper...\n")
    os.chdir(TARGET_DIR)
    
    system = platform.system().lower()
    
    if "windows" in system:
        script = "run.bat"
        cmd = ["cmd.exe", "/c", script]
    else:
        script = "./run.sh"
        cmd = [script]
        if os.path.exists("run.sh"):
            os.chmod("run.sh", 0o755)
            
    if not os.path.exists(script):
        print(f"[!] Critical Error: {script} not found in the cloned repository.")
        input("Press Enter to exit...")
        sys.exit(1)
        
    try:
        process = subprocess.Popen(cmd)
        process.wait()
    except KeyboardInterrupt:
        print("\n[*] Interrupted by user. Shutting down...")
        process.terminate()
    except Exception as e:
        print(f"[!] Error running the application: {e}")
        input("Press Enter to exit...")

def main():
    print("=========================================")
    print("          CatLabel Studio Launcher       ")
    print("=========================================\n")
    
    if not os.path.exists(TARGET_DIR):
        print(f"[*] Target directory '{TARGET_DIR}' not found.")
        print("[*] Initializing new installation...")
        clone_repo()
    else:
        if not os.path.exists(os.path.join(TARGET_DIR, ".git")):
            print(f"[!] The directory '{TARGET_DIR}' exists but is not a valid repository.")
            print("[!] Please delete or rename the folder and try again.")
            input("Press Enter to exit...")
            sys.exit(1)
        
        update_repo()
        
        if os.path.exists(os.path.join(TARGET_DIR, "env")):
            print("[*] Existing setup detected. Launching CatLabel...")
        else:
            print("[*] Repository found, but environment is missing.")
            print("[*] Setup will begin downloading dependencies now...")
            
    run_app()

if __name__ == "__main__":
    main()