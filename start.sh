#!/bin/bash
echo "Starting TiMini Print Server & Label Studio..."

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Virtual environment not found. Please run ./install.sh first."
    exit 1
fi

# Start backend in the background
echo "Starting backend on http://localhost:8000..."
python -m timiniprint &
BACKEND_PID=$!

# Function to clean up background process on exit
cleanup() {
    echo ""
    echo "Shutting down backend..."
    kill $BACKEND_PID
    exit
}
# Trap Ctrl+C (SIGINT) and termination signals to clean up the backend
trap cleanup SIGINT SIGTERM

# Start frontend
echo "Starting frontend on http://localhost:5173..."
cd frontend
npm run dev
