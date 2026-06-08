import threading

_ctx = threading.local()

def plog(msg: str) -> None:
    """Helper to log messages with current job id in the prefix."""
    prefix = getattr(_ctx, 'job_id', '?')
    print(f"[{prefix}] {msg}")
