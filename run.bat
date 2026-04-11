@echo off
setlocal
title CatLabel Bootstrapper

:: 1. Micromamba REQUIRES a root prefix to be set, even when using local prefixes (-p).
:: Without this, the 'create' command will fail silently.
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

    :: Verify that the download and extraction actually worked
    if not exist "bin\micromamba.exe" (
        echo ERROR: micromamba.exe was not found after extraction.
        goto error
    )

    echo [2/4] Creating isolated environment ^(Python ^& Node.js^)...
    bin\micromamba.exe create -p .\env -c conda-forge python=3.12 pip nodejs -y
    if errorlevel 1 goto error

    echo [3/4] Installing backend dependencies...
    bin\micromamba.exe run -p .\env python -m pip install -r requirements.txt
    if errorlevel 1 goto error

    echo [4/4] Building optimized frontend UI...
    :: Use pushd/popd instead of cd. It remembers where you were and guarantees you get back.
    pushd frontend
    
    :: Use npm.cmd explicitly. Windows doesn't handle calling extensionless batch files well through wrappers.
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
bin\micromamba.exe run -p .\env python -m catlabel

:: If the server crashes, this prevents the window from instantly vanishing
if errorlevel 1 goto error_server

:: End of successful script
pause
exit /b 0


:: ==========================================
:: ERROR HANDLING LABELS
:: ==========================================

:error_download
echo.
echo ERROR: Failed to download Micromamba. Please check your internet connection.
pause
exit /b 1

:error_extract
echo.
echo ERROR: Failed to extract Micromamba. The downloaded file might be corrupted.
pause
exit /b 1

:error_server
echo.
echo ERROR: The CatLabel server crashed or failed to start.
pause
exit /b 1

:error
echo.
echo =======================================================
echo ERROR: A critical error occurred during the setup.
echo Please review the text above to see what went wrong.
echo =======================================================
pause
exit /b 1
