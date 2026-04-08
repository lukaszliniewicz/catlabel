@echo off
echo Starting TiMini Print Server ^& Label Studio...

:: Activate virtual environment
if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment not found. Please run install.bat first.
    pause
    exit /b 1
)
call venv\Scripts\activate

:: Start backend in a new window so it doesn't block the terminal
echo Starting backend on http://localhost:8000...
start "TiMini Backend" cmd /c "python -m timiniprint"

:: Start frontend in the current window
echo Starting frontend on http://localhost:5173...
cd frontend
call npm run dev
