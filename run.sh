#!/bin/bash

# Exit immediately if a command fails
set -e

# Catch errors and print a clear, visible message instead of silently failing
trap 'echo -e "\n=======================================================\nERROR: A critical error occurred during the setup on line $LINENO.\nPlease review the output above to see what went wrong.\n======================================================="; exit 1' ERR

# 1. Explicitly set the root prefix to keep the installation portable
export MAMBA_ROOT_PREFIX="$(pwd)/data/mamba_root"

echo "=== CatLabel Bootstrapper ==="

if [ ! -d "env" ]; then
    echo "[1/4] Environment not found. Starting installation..."
    
    mkdir -p bin data
    if [ ! -f "bin/micromamba" ]; then
        echo "      Downloading standalone Micromamba..."
        OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
        ARCH="$(uname -m)"
        if [ "$ARCH" = "x86_64" ]; then ARCH="64"; fi
        if [ "$ARCH" = "aarch64" ]; then ARCH="aarch64"; fi
        if [ "$ARCH" = "arm64" ]; then ARCH="arm64"; fi
        
        # Download and extract just the binary directly into ./bin/
        curl -Ls "https://micro.mamba.pm/api/micromamba/${OS}-${ARCH}/latest" | tar -xvj -C bin bin/micromamba --strip-components=1
        
        # Ensure it has execute permissions
        chmod +x bin/micromamba
    fi

    # 2. Update Python to 3.12 and add python-lzo to Conda packages
    echo "[2/4] Creating isolated environment (Python 3.12, Node.js, Git, python-lzo)..."
    ./bin/micromamba create -p ./env -c conda-forge python=3.12 pip nodejs git python-lzo -y

    echo "[3/4] Installing backend dependencies..."
    ./bin/micromamba run -p ./env python -m pip install -r requirements.txt

    echo ""
    echo "----------------------------------------------------------------------"
    echo "OPTIONAL: Headless Browser (Third-Party API Integrations)"
    echo "If you plan to send print jobs to CatLabel from external scripts via"
    echo "the API, you need Playwright (~150MB download). Normal UI usage does NOT."
    read -p "Install Headless API support? [y/N]: " INSTALL_PLAYWRIGHT
    if [[ "$INSTALL_PLAYWRIGHT" =~ ^[Yy]$ ]]; then
        echo "      Installing Playwright and Headless Chromium..."
        ./bin/micromamba run -p ./env python -m pip install 'playwright>=1.40.0'
        export PLAYWRIGHT_BROWSERS_PATH=0
        ./bin/micromamba run -p ./env python -m playwright install chromium
    else
        echo "      Skipping Playwright installation."
    fi
    echo "----------------------------------------------------------------------"
    echo ""

    # 3. Use pushd/popd for safe directory navigation
    echo "[4/4] Building optimized frontend UI..."
    pushd frontend > /dev/null
    
    ../bin/micromamba run -p ../env npm install
    ../bin/micromamba run -p ../env npm run build
    
    popd > /dev/null

    echo "Installation complete!"
    echo "-----------------------------------"
fi

echo "Starting CatLabel Server (http://localhost:8000)..."
./bin/micromamba run -p ./env python -m catlabel
