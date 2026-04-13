@echo off
setlocal
title CatLabel Bootstrapper

:: 1. Micromamba REQUIRES a root prefix to be set
set "MAMBA_ROOT_PREFIX=%cd%\data\mamba_root"

echo === CatLabel Bootstrapper ===

if not exist "env\" (
    echo [1/4] Environment not found. Starting installation...

    if not exist "bin\micromamba.exe" (
        echo       Downloading standalone Micromamba...
        if not exist "bin" mkdir bin
        if not exist "data" mkdir data
        
        curl -L -o bin\micromamba.tar.bz2 "https://micro.mamba.pm/api/micromamba/win-64/latest"
        if errorlevel 1 goto error_download

        echo       Extracting Micromamba...
        tar -xf bin\micromamba.tar.bz2 -C bin Library/bin/micromamba.exe
        if errorlevel 1 goto error_extract

        move /Y bin\Library\bin\micromamba.exe bin\micromamba.exe >nul
        rmdir /S /Q bin\Library 2>nul
        del /Q bin\micromamba.tar.bz2 2>nul
    )

    if not exist "bin\micromamba.exe" (
        echo ERROR: micromamba.exe was not found after extraction.
        goto error
    )

    echo [2/4] Creating isolated environment ^(Python ^& Node.js^)...
    bin\micromamba.exe create -p .\env -c conda-forge python=3.11 pip nodejs -y
    if errorlevel 1 goto error

    echo [3/4] Installing backend dependencies...
    bin\micromamba.exe run -p .\env python -m pip install -r requirements.txt
    if errorlevel 1 goto error

    echo.
    echo ----------------------------------------------------------------------
    echo OPTIONAL: Headless Browser ^(Third-Party API Integrations^)
    echo If you plan to send print jobs to CatLabel from external scripts via 
    echo the API, you need Playwright ^(~150MB download^). Normal UI usage does NOT.
    set /p INSTALL_PLAYWRIGHT="Install Headless API support? [y/N]: "
    if /i "%INSTALL_PLAYWRIGHT%"=="y" (
        echo       Installing Playwright and Headless Chromium...
        bin\micromamba.exe run -p .\env python -m pip install playwright^>=1.40.0
        if errorlevel 1 goto error
        
        REM Setting this to 0 forces Playwright to install inside the local env folder
        set PLAYWRIGHT_BROWSERS_PATH=0
        bin\micromamba.exe run -p .\env python -m playwright install chromium
        if errorlevel 1 goto error
    ) else (
        echo       Skipping Playwright installation.
    )
    echo ----------------------------------------------------------------------
    echo.

    echo [4/4] Building optimized frontend UI...
    pushd frontend
    
    REM npm.cmd is required for Windows batch execution
    ..\bin\micromamba.exe run -p ..\env npm.cmd install
    if errorlevel 1 (
        popd
        goto error
    )
    
    ..\bin\micromamba.exe run -p ..\env npm.cmd run build
    if errorlevel 1 (
        popd
        goto error
    )
    
    popd

    echo Installation complete!
    echo -----------------------------------
)

echo Starting CatLabel Server (http://localhost:8000)...
set PLAYWRIGHT_BROWSERS_PATH=0
bin\micromamba.exe run -p .\env python -m catlabel

if errorlevel 1 goto error_server

pause
exit /b 0

:error_download
echo ERROR: Failed to download Micromamba.
pause
exit /b 1

:error_extract
echo ERROR: Failed to extract Micromamba.
pause
exit /b 1

:error_server
echo ERROR: The CatLabel server crashed or failed to start.
pause
exit /b 1

:error
echo =======================================================
echo ERROR: A critical error occurred during the setup.
echo =======================================================
pause
exit /b 1
