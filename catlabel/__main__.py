import uvicorn
import os

if __name__ == "__main__":
    port = int(os.environ.get("CATLABEL_PORT", 8000))
    uvicorn.run("catlabel.api.main:app", host="0.0.0.0", port=port, reload=False)
