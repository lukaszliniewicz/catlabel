#!/bin/bash
echo "Setting up TiMini Print Server & Label Studio..."

echo "1. Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "2. Installing backend dependencies..."
pip install -r requirements.txt

echo "3. Installing frontend dependencies..."
cd frontend
npm install
cd ..

echo ""
echo "Installation complete! Run ./start.sh to launch the app."
