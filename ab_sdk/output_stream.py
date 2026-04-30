# ab_sdk/output_stream.py

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

from .python_client import PythonRealtimeClient


class OutputStream:
    """Simple polling-based output stream.

    The SDK treats Python outputs as a realtime stream. The first transport here
    is polling for simplicity, but the class boundary makes it easy to swap in a
    socket/SSE/WebSocket transport later.
    """

    def __init__(
        self,
        python_client: PythonRealtimeClient,
        *,
        compile_id: str,
        poll_interval: float = 0.05,
        limit: int = 100,
    ) -> None:
        self.python_client = python_client
        self.compile_id = compile_id
        self.poll_interval = poll_interval
        self.limit = limit
        self.after_step: Optional[int] = None
        self._handlers: List[Callable[[Dict], None]] = []
        self._control_handlers: List[Callable[[Dict], None]] = []
        self.latest_item: Optional[Dict] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def on_item(self, handler: Callable[[Dict], None]) -> None:
        self._handlers.append(handler)
    
    def on_control(self, handler: Callable[[Dict], None]) -> None:
        self._control_handlers.append(handler)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name=f"OutputStream:{self.compile_id}")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _worker(self) -> None:
        while self._running:
            payload = self.python_client.get_outputs(
                compile_id=self.compile_id,
                after_step=self.after_step,
                limit=self.limit,
            )

            # CONTROL CHANNEL TO STOP STREAM
            control = payload.get("control")
            if control:
                print(f"[AB][CONTROL][STREAM] {control}")
                for handler in list(self._control_handlers):
                    handler(control)
                if control.get("command") == "stop":
                    self._running = False
                    return

            items = payload.get("items") or []
            if items:
                self.after_step = payload.get("next_after_step")
                for item in items:
                    self.latest_item = item
                    for handler in list(self._handlers):
                        handler(item)
            time.sleep(self.poll_interval)
