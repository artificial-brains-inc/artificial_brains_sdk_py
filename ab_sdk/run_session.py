"""Per‑run state container and event router.

The :class:`RunSession` encapsulates all of the information about a
running experiment (identified by a unique run ID) and exposes
conveniences for emitting input chunks, feedback rasters and reward
signals.  It also manages registration of event handlers for
telemetry and other realtime notifications.

You do not create a `RunSession` directly; instead it is returned
from :meth:`~ab_sdk.client.ABClient.start`.  Once created it holds
references to the originating :class:`~ab_sdk.client.ABClient`, the
HTTP API contract describing the IO interface and a live
Socket.IO client joined to the appropriate room.  You can attach
custom decoders, deviation policies and reward policies via
:meth:`set_decoder`, :meth:`set_deviation` and :meth:`set_reward`.

Instances of this class are not thread safe.  If you plan to
consume realtime events in multiple threads you should implement
appropriate synchronization in your handlers.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

import socketio

logger = logging.getLogger(__name__)


class RunSession:
    """Represents a single running brain session.

    Parameters
    ----------
    client: ABClient
        Reference to the client that created this session.  Used for
        fallback HTTP operations and error reporting.
    project_id: str
        The project identifier.
    run_id: str
        Unique identifier for this run returned by the server.
    contract: dict
        The run contract returned by the server on start.  Contains
        ``constants`` and ``io`` keys describing the IO interface.
    socket: socketio.Client
        A connected Socket.IO client already joined to the run room.
    namespace: str
        The namespace on the server to emit/receive events on (e.g. ``"/ab"``).
    """

    def __init__(self, client: Any, project_id: str, run_id: str,
                 contract: Dict[str, Any], socket: socketio.Client,
                 namespace: str) -> None:
        self.client = client
        self.project_id = project_id
        self.run_id = run_id
        self.contract = contract
        self.socket = socket
        self.namespace = namespace

        # parse constants
        consts = contract.get("constants", {})
        self.gamma: int = int(consts.get("gamma", 64))
        self.output_n: int = int(consts.get("outputWindowN", 32))
        self.feedback_n: int = int(consts.get("feedbackN", 128))

        # keep track of IO manifest
        self.io_inputs = {item["id"]: item for item in contract.get("io", {}).get("inputs", [])}
        self.io_outputs = {item["id"]: item for item in contract.get("io", {}).get("outputs", [])}
        self.io_feedback = {item["id"]: item for item in contract.get("io", {}).get("feedback", [])}
        self.stdp_layers: List[str] = list(contract.get("io", {}).get("stdp3", {}).get("layers", []))

        # plugin holders
        self.decoder_plugin: Optional[Any] = None
        self.deviation_plugin: Optional[Any] = None
        self.reward_plugin: Optional[Any] = None

        # event handlers registry
        self._cycle_handlers: List[Callable[[Dict[str, Any]], None]] = []
        self._io_need_handlers: List[Callable[[Dict[str, Any]], None]] = []
        self._cmd_handlers: List[Callable[[Dict[str, Any]], None]] = []

        # register default event handlers from contract (if any) when session is created
        self._register_socket_events()

    # ----------------------------------------------------------------------
    # Event registration API
    #
    # The run session receives events from the server via Socket.IO.  You
    # can register additional callbacks for cycle updates, IO needs and
    # command messages.  These callbacks will be called sequentially
    # from the Socket.IO event thread, so you should avoid blocking
    # operations inside handlers.
    #
    def on_cycle_update(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register a handler for cycle update events.

        The handler is called with the full telemetry payload as
        delivered by the server.  You can decode outputs, compute
        rewards and send feedback from within this callback.  Multiple
        handlers can be registered; they will be invoked in the order
        they were added.

        Parameters
        ----------
        handler: Callable[[dict], None]
            A callable accepting a telemetry dictionary.
        """
        self._cycle_handlers.append(handler)

    def on_io_need(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register a handler for IO need events.

        The handler is called with a payload of the form::

            {"runId": ..., "cycle": ..., "needs": [...], "deadlineMs": ...}

        Your handler should respond by calling :meth:`send_input_chunk` or
        :meth:`send_feedback_raster` for each requested input.  The SDK
        provides :class:`~ab_sdk.input_streamer.InputStreamer` which
        implements this logic for you.
        """
        self._io_need_handlers.append(handler)

    def on_robot_cmd(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register a handler for robot command events.

        This is only necessary if your server still returns
        `robot:cmd` events (legacy behaviour).  When mapping and
        decoding move into the SDK the server will stop sending
        commands and instead only emit output spikes via
        ``cycle:update``.
        """
        self._cmd_handlers.append(handler)

    def set_decoder(self, decoder: Any) -> None:
        """Attach a decoder plugin.

        The decoder must implement a `decode(outputs, context)` method
        which receives a dictionary mapping output IDs to a matrix
        ``(gamma x outputN)`` and returns a command dictionary
        ``{'dq': [...], 'dg': float}``.  See
        :class:`~ab_sdk.plugins.decoder.BaseDecoder` for details.

        Parameters
        ----------
        decoder: Any
            An object implementing a ``decode`` method.
        """
        self.decoder_plugin = decoder

    def set_deviation(self, deviation_policy: Any) -> None:
        """Attach a deviation policy plugin.

        The deviation policy must implement a ``compute(telemetry)``
        method returning a mapping from feedback input IDs to lists of
        floats of length ``gamma`` in the range ``[-1,1]``.  See
        :class:`~ab_sdk.plugins.deviation.BaseDeviation`.
        """
        self.deviation_plugin = deviation_policy

    def set_reward(self, reward_policy: Any) -> None:
        """Attach a reward policy plugin.

        The reward policy must implement a ``compute(telemetry)``
        method returning a tuple ``(global_reward, by_layer_dict)``
        where ``global_reward`` is a float in ``[0,1]`` and
        ``by_layer_dict`` maps layer names to floats in ``[0,1]``.  See
        :class:`~ab_sdk.plugins.reward.BaseReward`.
        """
        self.reward_plugin = reward_policy

    # ----------------------------------------------------------------------
    # Emission helpers
    #
    def send_input_chunk(self, input_id: str, kind: str, seq: int, t: float,
                          fmt: str, meta: Dict[str, Any], data: bytes) -> None:
        """Emit a raw input chunk over the realtime channel.

        This is a generic helper used by the input streamer.  The
        payload shape matches the specification in the README.  You
        normally should not call this directly; use
        :class:`~ab_sdk.input_streamer.InputStreamer` instead.
        """
        payload = {
            "runId": self.run_id,
            "inputId": input_id,
            "kind": kind,
            "seq": int(seq),
            "t": float(t),
            "format": fmt,
            "meta": meta,
            "data": data,
        }
        logger.debug("Sending input chunk: %s", {k: payload[k] for k in payload if k != "data"})
        self.socket.emit("io:chunk", payload, namespace=self.namespace)

    def send_feedback_raster(self, input_id: str, raster: Iterable[float],
                             cycle: int) -> None:
        """Send a feedback raster for the given feedback input.

        The raster should be a flat iterable of length ``gamma * feedbackN``
        (e.g. a list or a numpy array).  Values should be floats in
        ``[-1,1]``.  The caller is responsible for constructing the
        raster using :func:`~ab_sdk.utils.feedback.build_feedback_raster`.

        Parameters
        ----------
        input_id: str
            The identifier of the feedback input to send.
        raster: Iterable[float]
            A flat sequence containing ``gamma * feedbackN`` floats.
        cycle: int
            The cycle number associated with this feedback (optional,
            included in ``meta`` for debugging).
        """
        # convert to bytes – we pack as little-endian float32 values
        import array
        arr = array.array('f', raster)
        data_bytes = arr.tobytes()
        meta = {"T": self.gamma, "N": self.feedback_n, "cycle": cycle}
        self.send_input_chunk(input_id=input_id, kind="Feedback",
                              seq=int(time.time() * 1000),
                              t=time.time(), fmt="raster_f32",
                              meta=meta, data=data_bytes)

    def send_reward(self, global_reward: float, by_layer: Dict[str, float],
                    cycle: int) -> None:
        """Send reward information to the server.

        Only STDP3 layers listed in ``self.stdp_layers`` are included
        in the payload; missing entries are filled with ``global_reward``.
        """
        # sanitize and fill missing
        payload_layers: Dict[str, float] = {}
        for layer in self.stdp_layers:
            val = by_layer.get(layer, global_reward)
            # clamp to [0,1]
            val = max(0.0, min(1.0, float(val)))
            payload_layers[layer] = val
        payload = {
            "runId": self.run_id,
            "cycle": cycle,
            "globalReward": max(0.0, min(1.0, float(global_reward))),
            "byLayer": payload_layers,
        }
        logger.debug("Sending reward: %s", payload)
        self.socket.emit("learn:reward", payload, namespace=self.namespace)

    def close(self) -> None:
        """Disconnect the Socket.IO client.

        This method should be called when you are finished with the
        session.  It will detach any event handlers and leave the run
        room.  Subsequent operations on this session may fail.
        """
        try:
            if self.socket.connected:
                logger.info("Disconnecting session %s", self.run_id)
                self.socket.disconnect(namespace=self.namespace)
        except Exception as exc:
            logger.warning("Error disconnecting session: %s", exc)

    # ----------------------------------------------------------------------
    # Internal: register socket event handlers
    #
    def _register_socket_events(self) -> None:
        """Setup internal Socket.IO event dispatching.

        This method attaches handlers to the underlying Socket.IO client
        for the known event types (``cycle:update``, ``io:need``,
        ``robot:cmd``).  When events are received the registered
        callbacks are invoked sequentially.
        """

        @self.socket.on("cycle:update", namespace=self.namespace)
        def _on_cycle_update(payload: Dict[str, Any]) -> None:
            logger.debug("Received cycle update: cycle=%s", payload.get("cycle"))
            for handler in self._cycle_handlers:
                try:
                    handler(payload)
                except Exception as exc:
                    logger.exception("Error in cycle update handler: %s", exc)

        @self.socket.on("io:need", namespace=self.namespace)
        def _on_io_need(payload: Dict[str, Any]) -> None:
            logger.debug("Received IO need: %s", payload)
            for handler in self._io_need_handlers:
                try:
                    handler(payload)
                except Exception as exc:
                    logger.exception("Error in IO need handler: %s", exc)

        @self.socket.on("robot:cmd", namespace=self.namespace)
        def _on_robot_cmd(payload: Dict[str, Any]) -> None:
            logger.debug("Received robot command: %s", payload)
            for handler in self._cmd_handlers:
                try:
                    handler(payload)
                except Exception as exc:
                    logger.exception("Error in robot command handler: %s", exc)
