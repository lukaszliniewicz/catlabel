@echo off
echo Setting up TiMini Print Server ^& Label Studio...

echo 1. Setting up Python virtual environment...
python -m venv venv
call venv\Scripts\activate

echo 2. Installing backend dependencies...
pip install -r requirements.txt

echo 3. Installing frontend dependencies...
cd frontend
call npm install
cd ..

echo.
echo Installation complete! Run start.bat to launch the app.
pause
