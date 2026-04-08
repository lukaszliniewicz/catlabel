import uvicorn

if __name__ == "__main__":
    uvicorn.run("timiniprint.app:app", host="0.0.0.0", port=8000, reload=False)
