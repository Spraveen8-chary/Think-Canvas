import uvicorn

from .core.config import get_settings

if __name__ == "__main__":
    # 127.0.0.1 only: nothing is reachable from other computers.
    # log_config=None keeps our own logging setup (console + logs/think-canvas.log).
    uvicorn.run("backend.main:app", host="127.0.0.1", port=get_settings().port, log_config=None)
