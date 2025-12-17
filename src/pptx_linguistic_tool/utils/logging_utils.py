# src/utils/logging_utils.py
from __future__ import annotations
from typing import Callable, Optional

def safe_log(log: Optional[Callable[[str], None]], msg: str) -> None:
    """Log without ever raising (works with GUI log callbacks or plain print)."""
    try:
        (log or (lambda *_: None))(msg)
    except Exception:
        pass

def log_and_output(
    log: Optional[Callable[[str], None]],
    output: Optional[Callable[[str], None]],
    message: str,
) -> None:
    """Convenience for GUI: send to both log and output panes, never raise."""
    safe_log(log, message)
    try:
        (output or (lambda *_: None))(message)
    except Exception:
        pass
