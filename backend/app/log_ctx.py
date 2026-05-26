import threading

_ctx = threading.local()

def plog(msg: str) -> None:
    prefix = getattr(_ctx, 'job_id', '?')
    print(f"[{prefix}] {msg}")
