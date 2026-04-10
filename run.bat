@echo off
setlocal
echo === TiMini Print Bootstrapper ===

if not exist "env\" (
    echo [1/4] Environment not found. Starting installation...

    if not exist "bin\micromamba.exe" (
        echo       Downloading standalone Micromamba...
        mkdir bin 2>nul
        mkdir data 2>nul
        curl -L -o bin\micromamba.tar.bz2 "https://micro.mamba.pm/api/micromamba/win-64/latest"
        REM Windows 10+ has a built in tar command
        tar -xf bin\micromamba.tar.bz2 -C bin Library/bin/micromamba.exe
        move /Y bin\Library\bin\micromamba.exe bin\micromamba.exe >nul
        rmdir /S /Q bin\Library 2>nul
        del /Q bin\micromamba.tar.bz2 2>nul
    )

    echo [2/4] Creating isolated environment ^(Python ^& Node.js^)...
    bin\micromamba.exe create -p .\env -c conda-forge python=3.11 pip nodejs -y
    if errorlevel 1 exit /b 1

    echo [3/4] Installing backend dependencies...
    bin\micromamba.exe run -p .\env pip install -r requirements.txt
    if errorlevel 1 exit /b 1

    echo [4/4] Building optimized frontend UI...
    cd frontend
    ..\bin\micromamba.exe run -p ..\env npm install
    if errorlevel 1 exit /b 1
    ..\bin\micromamba.exe run -p ..\env npm run build
    if errorlevel 1 exit /b 1
    cd ..

    echo Installation complete!
    echo -----------------------------------
)

echo Starting TiMini Print Server (http://localhost:8000)...
bin\micromamba.exe run -p .\env python -m timiniprint
