#!/bin/bash
set -e

echo "=== TiMini Print Bootstrapper ==="

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
    fi

    echo "[2/4] Creating isolated environment (Python & Node.js)..."
    ./bin/micromamba create -p ./env -c conda-forge python=3.11 pip nodejs -y

    echo "[3/4] Installing backend dependencies..."
    ./bin/micromamba run -p ./env python -m pip install -r requirements.txt

    echo "[4/4] Building optimized frontend UI..."
    cd frontend
    ../bin/micromamba run -p ../env npm install
    ../bin/micromamba run -p ../env npm run build
    cd ..

    echo "Installation complete!"
    echo "-----------------------------------"
fi

echo "Starting TiMini Print Server (http://localhost:8000)..."
./bin/micromamba run -p ./env python -m timiniprint
