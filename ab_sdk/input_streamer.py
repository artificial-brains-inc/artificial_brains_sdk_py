"""Automatic streaming of sensor inputs to the brain.

The :class:`InputStreamer` listens for `io:need` events from the
server and responds by invoking user provided callbacks to obtain the
requested input data.  Each callback should return a dictionary
containing a `format` string (e.g. ``"jpeg"`` or ``"pcm16"``), a
metadata dictionary and a `data` buffer with the raw bytes.  The
streamer will then emit an ``io:chunk`` event to the server with the
appropriate fields filled in.

Example usage::

    streamer = InputStreamer(run_session)
    # Attach a provider for the RGB camera
    def get_frame() -> dict:
        img_bytes = capture_frame_from_camera()
        return {
            'format': 'jpeg',
            'meta': {'width': 640, 'height': 480},
            'data': img_bytes,
        }
    streamer.register_input('cam_rgb', 'Image', get_frame)
    # Register a microphone provider by kind
    def get_audio() -> dict:
        pcm = capture_audio_chunk()
        return {
            'format': 'pcm16',
            'meta': {'sampleRate': 16000, 'channels': 1},
            'data': pcm,
        }
    streamer.register_kind('Audio', get_audio)
    # Start listening
    streamer.start()

The streamer keeps internal sequence numbers for each input ID and
timestamp to help the server assemble streaming data.  If no provider
is registered for a requested input then a warning is logged and the
SDK does nothing; the server will fall back to a random or default
assignment for that input.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .run_session import RunSession

logger = logging.getLogger(__name__)

# Type alias for the provider function return value
ProviderReturn = Dict[str, Any]
ProviderFunc = Callable[[], ProviderReturn]


class InputStreamer:
    """Responds to IO needs by streaming sensor data.

    Parameters
    ----------
    session: RunSession
        The active run session to stream inputs for.
    """

    def __init__(self, session: RunSession) -> None:
        self.session = session
        # mapping from specific input IDs to provider functions
        self._id_providers: Dict[str, ProviderFunc] = {}
        # mapping from kinds (e.g. "Image", "Audio") to provider functions
        self._kind_providers: Dict[str, ProviderFunc] = {}
        # keep a per‑input sequence counter
        self._seq: Dict[str, int] = {}
        self._registered = False

    def register_input(self, input_id: str, kind: str, provider: ProviderFunc) -> None:
        """Register a provider function for a specific input ID.

        If both an ID and a kind provider exist, the ID provider takes
        precedence.  The provider function must accept no arguments and
        return a dictionary with keys ``format``, ``meta`` and ``data``.
        """
        if not input_id:
            raise ValueError("input_id must be non‑empty")
        if not callable(provider):
            raise ValueError("provider must be callable")
        self._id_providers[input_id] = provider
        # store kind for informational purposes
        self.session.io_inputs.setdefault(input_id, {"kind": kind})
        logger.info("Registered provider for input %s (kind=%s)", input_id, kind)

    def register_kind(self, kind: str, provider: ProviderFunc) -> None:
        """Register a provider function for all inputs of a given kind.

        The provider will be used for any input ID whose kind matches
        this value and which does not have a specific provider
        registered via :meth:`register_input`.
        """
        if not kind:
            raise ValueError("kind must be non‑empty")
        if not callable(provider):
            raise ValueError("provider must be callable")
        self._kind_providers[kind] = provider
        logger.info("Registered provider for kind %s", kind)

    def _next_seq(self, input_id: str) -> int:
        """Return and increment the next sequence number for the given input."""
        seq = self._seq.get(input_id, 0) + 1
        self._seq[input_id] = seq
        return seq

    def start(self) -> None:
        """Begin listening for IO need events.

        This attaches a handler on the associated :class:`RunSession`
        which will be called whenever an ``io:need`` event arrives.  If
        you register providers after calling ``start`` they will be
        respected on subsequent events.
        """
        if self._registered:
            logger.warning("InputStreamer.start() called multiple times; ignoring")
            return
        self.session.on_io_need(self._handle_io_need)
        self._registered = True
        logger.debug("InputStreamer started for run %s", self.session.run_id)

    def _handle_io_need(self, payload: Dict[str, Any]) -> None:
        """Internal handler for IO need events.

        For each requested input the corresponding provider is invoked
        and an ``io:chunk`` event is emitted via the session.  If no
        provider is found then a warning is logged.
        """
        needs = payload.get("needs", [])
        cycle = payload.get("cycle")
        for need in needs:
            input_id = need.get("id")
            kind = need.get("kind")
            if not input_id:
                continue
            provider = self._id_providers.get(input_id)
            if provider is None:
                provider = self._kind_providers.get(kind)
            if provider is None:
                logger.warning(
                    "No provider registered for input %s (kind=%s); skipping",
                    input_id, kind)
                continue
            try:
                result = provider()
                if not isinstance(result, dict):
                    raise TypeError("provider must return a dict with keys 'format','meta','data'")
                fmt = result.get("format")
                meta = result.get("meta") or {}
                data = result.get("data")
                if not isinstance(data, (bytes, bytearray)):
                    raise TypeError("provider returned 'data' which is not bytes")
                # update meta with cycle for debugging
                meta = dict(meta)
                meta.setdefault("cycle", cycle)
                seq = self._next_seq(input_id)
                t = time.time()
                self.session.send_input_chunk(
                    input_id=input_id,
                    kind=kind,
                    seq=seq,
                    t=t,
                    fmt=fmt,
                    meta=meta,
                    data=data,
                )
                logger.debug("Streamed input %s seq=%s at t=%f", input_id, seq, t)
            except Exception as exc:
                logger.exception("Error in provider for %s: %s", input_id, exc)
