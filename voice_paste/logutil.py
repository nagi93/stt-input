"""Append-only error log: failures must never be silent.

The app runs under pythonw (no console), so an exception that is only
printed is an exception nobody ever sees — several bugs survived that
way.  Anything user-visible that fails also lands here, at
``logs/app.log`` next to the app, with a timestamp and traceback.
"""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

from .config import APP_DIR

_LOG = Path(APP_DIR) / "logs" / "app.log"
_LOCK = threading.Lock()
_MAX_BYTES = 1_000_000


def log_error(context: str, exc: BaseException | None = None,
              message: str = "") -> None:
    try:
        with _LOCK:
            _LOG.parent.mkdir(parents=True, exist_ok=True)
            if _LOG.exists() and _LOG.stat().st_size > _MAX_BYTES:
                _LOG.write_text("", encoding="utf-8")
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            detail = ""
            if exc is not None:
                detail = "".join(traceback.format_exception(
                    type(exc), exc, exc.__traceback__)).rstrip()
            with _LOG.open("a", encoding="utf-8") as f:
                f.write(f"[{ts}] {context} {message}\n{detail}\n")
    except Exception:
        pass  # logging must never take the app down
