"""Start SpriteKiln: python backend/run.py [--port 7788] [--host 127.0.0.1]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7788)
    ap.add_argument("--reload", action="store_true")
    a = ap.parse_args()
    uvicorn.run("app.main:app", host=a.host, port=a.port, reload=a.reload, log_level="info")
