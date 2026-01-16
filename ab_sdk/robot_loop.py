"""High level loop for controlling a robot during a run.

The :class:`RobotLoop` coordinates sending the robot's observed state to
the server, decoding the output spikes returned from the brain and
applying the resulting command to your hardware.  It integrates with
the :class:`~ab_sdk.run_session.RunSession` lifecycle and uses
callbacks supplied by the user for state acquisition and command
execution.

Example usage::

    def get_robot_state():
        return { 'q': current_joint_positions(), 'dq': current_joint_vels(), 'grip': {'pos': gripper_pos}, 'dt': dt }

    def apply_command(cmd):
        set_joint_targets(cmd['dq'])
        set_gripper(cmd['dg'])

    loop = RobotLoop(session, state_provider=get_robot_state, command_executor=apply_command)
    loop.run_forever()

In this example the brain's decoded commands are applied directly to a
hardware or simulated robot.  If you are still letting the server
generate ``robot:cmd`` events then you can omit the decoder plugin
and use the command handler registered on the session instead.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from .run_session import RunSession

logger = logging.getLogger(__name__)


class RobotLoop:
    """Manage the control loop for a robot.

    The loop periodically collects the robot's current state and sends
    it to the server via the session's realtime channel.  When cycle
    update events arrive the associated decoder plugin (if attached) is
    invoked to produce a command which is then passed to the
    user‑supplied command executor.

    Parameters
    ----------
    session: RunSession
        The active run session to which robot states and commands should
        be associated.
    state_provider: Callable[[], Dict[str, Any]]
        A callback returning the current robot state.  This should
        return a dictionary with keys ``q`` (joint positions), ``dq``
        (joint velocities), ``grip`` (dict with ``pos``) and ``dt``
        (time delta since last call).  All fields are optional;
        missing values are simply omitted from the state payload.  The
        provider is invoked on a background thread at the configured
        tick frequency.
    command_executor: Callable[[Dict[str, Any]], None]
        A callback invoked with a command dictionary returned by the
        decoder plugin.  The dictionary has keys ``dq`` (array of
        joint deltas), ``dg`` (scalar gripper command) and any
        additional keys defined by your decoder.  This callback should
        apply the command to the actual robot.
    tick_hz: float, optional
        The frequency in Hz at which to send robot states to the
        server.  Defaults to 20Hz.  Set to 0 to disable periodic
        sending (state must then be sent manually).
    """

    def __init__(self, session: RunSession,
                 state_provider: Callable[[], Dict[str, Any]],
                 command_executor: Callable[[Dict[str, Any]], None],
                 tick_hz: float = 20.0) -> None:
        self.session = session
        self.state_provider = state_provider
        self.command_executor = command_executor
        self.tick_hz = tick_hz
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # register to receive cycle updates and decode commands
        self.session.on_cycle_update(self._on_cycle_update)

    def _on_cycle_update(self, telemetry: Dict[str, Any]) -> None:
        """Handle cycle update events by decoding commands and applying them.

        If a decoder plugin is attached to the session then this
        callback will build a dictionary of output matrices keyed by
        output ID and invoke the plugin's ``decode`` method.  The
        resulting command dictionary is passed to the supplied
        ``command_executor``.  Any exceptions raised by the decoder
        are caught and logged; command execution is skipped on error.
        """
        decoder = self.session.decoder_plugin
        if decoder is None:
            # nothing to do; maybe server will send robot:cmd
            return
        outputs = telemetry.get("outputs", [])
        # build a mapping from output id to matrix (gamma x outputN)
        output_matrices: Dict[str, List[List[int]]] = {}
        for entry in outputs:
            try:
                t_step, out_id, bits = entry
            except ValueError:
                continue
            if out_id not in output_matrices:
                # initialize matrix with zeros
                output_matrices[out_id] = [[0] * self.session.output_n for _ in range(self.session.gamma)]
            # assign row
            row = output_matrices[out_id][int(t_step)]
            # bits may be shorter than output_n; pad
            for i in range(min(len(bits), self.session.output_n)):
                row[i] = 1 if bits[i] else 0
        try:
            command = decoder.decode(output_matrices, context={
                "telemetry": telemetry,
                "session": self.session,
            })
            if command is not None:
                logger.debug("Decoded command: %s", command)
                self.command_executor(command)
        except Exception as exc:
            logger.exception("Decoder error: %s", exc)

    def _send_robot_state(self) -> None:
        """Collect the current robot state and emit it to the server."""
        try:
            state = self.state_provider() or {}
            payload = {"runId": self.session.run_id, "state": state}
            self.session.socket.emit("robot:state", payload, namespace=self.session.namespace)
            logger.debug("Sent robot state: %s", payload)
        except Exception as exc:
            logger.exception("Error collecting or sending robot state: %s", exc)

    def run_forever(self) -> None:
        """Start the control loop and block until stopped.

        This method spawns a background thread which periodically
        acquires robot state and sends it to the server.  It then
        blocks on the main thread, sleeping indefinitely.  To stop the
        loop call :meth:`stop` from another thread or signal handler.
        """
        if self._running:
            logger.warning("RobotLoop.run_forever() called while already running")
            return
        self._running = True
        if self.tick_hz > 0:
            interval = 1.0 / float(self.tick_hz)
        else:
            interval = 0.0
        # define worker function
        def _worker() -> None:
            while self._running:
                if interval > 0:
                    start = time.time()
                    self._send_robot_state()
                    elapsed = time.time() - start
                    sleep_time = max(0.0, interval - elapsed)
                    time.sleep(sleep_time)
                else:
                    time.sleep(0.1)
        # start worker thread
        self._thread = threading.Thread(target=_worker, name="RobotLoopWorker")
        self._thread.daemon = True
        self._thread.start()
        logger.info("Robot loop started")
        try:
            while self._running:
                time.sleep(1)
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the control loop."""
        if not self._running:
            return
        self._running = False
        logger.info("Stopping robot loop")
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
