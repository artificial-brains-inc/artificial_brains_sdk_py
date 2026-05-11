# ab_sdk/robot_loop.py

from __future__ import annotations

import sys
import threading
import time
import httpx
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from .session import RealtimeSession


@dataclass
class RewardPayload:
    """Reward payload returned by the controller.

    The controller computes rewards.
    The SDK validates/routs them through the session.

    Accepted shape:
        RewardPayload(
            global_reward=0.5,
            local_rewards={"on_line": 1.0, "avoid_obstacle": 0.25},
            meta={"source": "epuck"}
        )

    Equivalent dict form also accepted by RobotLoop:
        {
            "global": 0.5,
            "local": {"on_line": 1.0},
            "meta": {...}
        }
    """

    global_reward: Optional[float] = None
    global_drive: Optional[float] = None
    local_rewards: dict[str, float] = field(default_factory=dict)
    local_drives: dict[str, float] = field(default_factory=dict)
    meta: Optional[dict[str, Any]] = None


class RobotLoop:
    """SDK-managed robot loop for robots / Webots controllers.

    Boundary:
    - controller owns robot logic:
        * collect inputs
        * apply outputs
        * calculate rewards
    - SDK owns:
        * scheduling
        * publishing inputs
        * publishing rewards
        * command callback wiring

    `state_provider` returns:
        {
            "camera": ...,
            "proprioception": ...,
        }

    or per-sensor config dicts:
        {
            "ps0": {
                "signal": 1234.0,
                "mode": "positive_scalar_population",
                "vmax": 4095.0,
                "radius": 1,
            }
        }

    Keys are expected to match names in session.input_map.by_sensor.

    `reward_provider` returns one of:
        - None
        - RewardPayload(...)
        - {
              "global": 0.2,
              "local": {"on_line": 1.0},
              "meta": {...}
          }

    Unknown sensors / local rewards can either raise or be skipped,
    depending on `strict`.
    """

    def __init__(
        self,
        session: RealtimeSession,
        *,
        state_provider: Callable[[], Mapping[str, Any]],
        sensor_providers: Optional[Mapping[str, Callable[[], Any]]] = None,
        input_mode: str = "batch",
        reward_provider: Optional[Callable[[], Any]] = None,
        command_executor: Optional[Callable[[Any], None]] = None,
        tick_hz: float = 20.0,
        input_hz: float = 100.0,
        reward_hz: float = 20.0,
        encoder_mode: str = "vector_f32",
        strict: bool = True,
        auto_register_command_handler: bool = True,
        checkpoint_every_ticks: int = 500,
        exploratory_rewards: bool = False,
        exploratory_output_ratio: float = 0.5,
        exploratory_min_abs_delta: float = 0.01,
    ) -> None:
        self.session = session
        self.state_provider = state_provider
        self.sensor_providers = dict(sensor_providers or {})
        self.input_mode = input_mode
        self.reward_provider = reward_provider
        self.command_executor = command_executor
        self.tick_hz = tick_hz
        self.input_hz = float(input_hz)
        self.reward_hz = float(reward_hz)
        self.encoder_mode = encoder_mode
        self.strict = strict
        self.checkpoint_every_ticks = int(checkpoint_every_ticks or 0)
        self._tick_count = 0
        self.exploratory_rewards = bool(exploratory_rewards)
        self.exploratory_output_ratio = float(exploratory_output_ratio)
        self.exploratory_min_abs_delta = float(exploratory_min_abs_delta)
        self._exploration_complete = False
        self._pending_layer_rewards: dict[str, dict[str, Any]] = {}
        self._reward_lock = threading.Lock()

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._input_flush_thread: Optional[threading.Thread] = None
        self._input_threads: list[threading.Thread] = []
        self._reward_thread: Optional[threading.Thread] = None

        self._input_buffer: dict[str, dict[str, Any]] = {}
        self._input_lock = threading.Lock()
        self._input_send_seq = 0

        if auto_register_command_handler:
            self.session.on_command(self._handle_command)
        
        self._user_command_executor = command_executor

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self.input_mode == "parallel":
            self._start_parallel_inputs()
            self._start_input_flush_loop()
            self._start_reward_loop()
        else:
            self._thread = threading.Thread(
                target=self._worker,
                daemon=True,
                name=f"RobotLoop:{self.session.compile_id}",
            )
            self._thread.start()

    def stop(self) -> None:
        self._running = False
        for thread in self._input_threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2.0)
        self._input_threads = []

        if self._reward_thread:
            if self._reward_thread is not threading.current_thread():
                self._reward_thread.join(timeout=2.0)
            self._reward_thread = None
        
        if self._input_flush_thread:
            if self._input_flush_thread is not threading.current_thread():
                self._input_flush_thread.join(timeout=2.0)
            self._input_flush_thread = None
            
        if self._thread:
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=2.0)
            self._thread = None

    def run_forever(self) -> None:
        self.start()
        try:
            while self._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _worker(self) -> None:
        interval = 1.0 / self.tick_hz if self.tick_hz > 0 else 0.05

        try:
            while self._running:
                started = time.time()

                self._publish_inputs()
                self._publish_rewards()

                elapsed = time.time() - started
                time.sleep(max(0.0, interval - elapsed))
        except Exception as exc:
            self._running = False
            print(f"[AB] RobotLoop crashed: {exc}", file=sys.stderr)
            try:
                self.session.stop(notify_node=True)
            except Exception as stop_exc:
                print(
                    f"[AB] failed to stop session after RobotLoop crash: {stop_exc}",
                    file=sys.stderr,
                )
            raise

    def _publish_inputs(self) -> None:
        payload = self.state_provider() or {}
        if not isinstance(payload, Mapping):
            raise TypeError("state_provider must return a mapping of sensor -> signal")

        known_sensors = self.session.input_map.by_sensor

        for sensor, signal in payload.items():
            self._publish_one_input(sensor, signal)

    def _publish_rewards(self) -> None:
        if self.reward_provider is None:
            return

        raw = self.reward_provider()
        if raw is None:
            return

        reward = self._normalize_reward_payload(raw)
        reward = self._apply_exploratory_reward_gate(reward)
 

        if reward.global_reward is not None:
            self.session.send_global_reward(
                float(reward.global_reward),
                drive=reward.global_drive,
                meta=reward.meta,
            )

        if reward.local_rewards:
            routed: dict[str, float] = {}

            for from_output, value in reward.local_rewards.items():
                bindings = self.session.reward_map.get_by_output(from_output)

                if not bindings:
                    if self.strict:
                        raise KeyError(f"unknown local reward output '{from_output}'")
                    continue

                routed[str(from_output)] = float(value)

            if routed:
                layer_rewards = self.session.route_local_rewards_to_layers(
                    routed,
                    drives=reward.local_drives,
                    meta=reward.meta,
                )

                with self._reward_lock:
                    # overwrite: one latest reward per layer
                    self._pending_layer_rewards.update(layer_rewards)

    def _start_parallel_inputs(self) -> None:
        if not self.sensor_providers:
            raise ValueError(
                "input_mode='parallel' requires sensor_providers={sensor: callable}"
            )

        for sensor, provider in self.sensor_providers.items():
            if sensor not in self.session.input_map.by_sensor:
                if self.strict:
                    raise KeyError(f"unknown sensor '{sensor}'")
                continue

            thread = threading.Thread(
                target=self._sensor_worker,
                args=(sensor, provider),
                daemon=True,
                name=f"ABSensor:{sensor}",
            )
            self._input_threads.append(thread)
            thread.start()


    def _start_reward_loop(self) -> None:
        if self.reward_provider is None:
            return

        self._reward_thread = threading.Thread(
            target=self._reward_worker,
            daemon=True,
            name=f"ABRewards:{self.session.compile_id}",
        )
        self._reward_thread.start()


    def _sensor_worker(self, sensor: str, provider: Callable[[], Any]) -> None:
        interval = 1.0 / self.input_hz if self.input_hz > 0 else 0.01

        while self._running:
            started = time.time()

            try:
                signal = provider()
                self._publish_one_input(sensor, signal)
            except httpx.TimeoutException as exc:
                print(
                    f"[AB][INPUT][TIMEOUT] sensor={sensor} error={exc}",
                    flush=True,
                )
            except Exception as exc:
                if self.strict:
                    print(
                        f"[AB][INPUT][ERROR] sensor={sensor} error={exc}",
                        file=sys.stderr,
                        flush=True,
                    )
                    raise
                print(
                    f"[AB][INPUT][SKIP] sensor={sensor} error={exc}",
                    file=sys.stderr,
                    flush=True,
                )

            elapsed = time.time() - started
            time.sleep(max(0.0, interval - elapsed))


    def _reward_worker(self) -> None:
        interval = 1.0 / self.reward_hz if self.reward_hz > 0 else 0.25

        while self._running:
            started = time.time()

            try:
                self._publish_reward_cycle()
            except httpx.TimeoutException as exc:
                print(f"[AB][REWARD][TIMEOUT] {type(exc).__name__}: {exc}", flush=True)
            except Exception as exc:
                print(f"[AB][REWARD][SEND_ERROR] {type(exc).__name__}: {exc}", flush=True)

            elapsed = time.time() - started
            time.sleep(max(0.0, interval - elapsed))

    def _publish_reward_cycle(self) -> None:
        if self.reward_provider is None:
            return

        raw = self.reward_provider()
        if raw is None:
            return

        reward = self._normalize_reward_payload(raw)
        reward = self._apply_exploratory_reward_gate(reward)

        layer_rewards: dict[str, dict[str, Any]] = {}

        if reward.local_rewards:
            routed: dict[str, float] = {}

            for from_output, value in reward.local_rewards.items():
                bindings = self.session.reward_map.get_by_output(from_output)

                if not bindings:
                    if self.strict:
                        raise KeyError(f"unknown local reward output '{from_output}'")
                    continue

                routed[str(from_output)] = float(value)

            if routed:
                layer_rewards = self.session.route_local_rewards_to_layers(
                    routed,
                    drives=reward.local_drives,
                    meta=reward.meta,
                )

        # One reward cycle:
        # 1. global reward/modulatory signal
        # 2. local layer rewards immediately after
        if reward.global_reward is not None:
            self.session.send_global_reward(
                float(reward.global_reward),
                drive=reward.global_drive,
                meta=reward.meta,
            )

        if layer_rewards:
            self.session.send_layer_rewards_batch(layer_rewards)



    def _publish_one_input(self, sensor: str, signal: Any) -> None:
        if sensor not in self.session.input_map.by_sensor:
            if self.strict:
                raise KeyError(f"unknown sensor '{sensor}'")
            return

        if isinstance(signal, Mapping):
            encoded = self.session.encoder.encode(
                sensor,
                signal.get("signal"),
                mode=signal.get("mode", self.encoder_mode),
                vmax=signal.get("vmax"),
                vmin=signal.get("vmin"),
                absmax=signal.get("absmax"),
                radius=int(signal.get("radius", 1)),
                meta=signal.get("meta"),
            )
        else:
            encoded = self.session.encoder.encode(
                sensor,
                signal,
                mode=self.encoder_mode,
            )

        event = {
            "target": encoded.target,
            "payload": encoded.payload,
            "meta": encoded.meta,
        }

        if self.input_mode == "parallel":
            with self._input_lock:
                self._input_buffer[encoded.target] = event
        else:
            self.session.input_client.send_input(
                payload={
                    "compileId": self.session.compile_id,
                    "events": [event],
                }
            )
    
    def _start_input_flush_loop(self) -> None:
        self._input_flush_thread = threading.Thread(
            target=self._input_flush_worker,
            daemon=True,
            name=f"ABInputFlush:{self.session.compile_id}",
        )
        self._input_flush_thread.start()

    def _send_input_batch_async(self, batch: list[dict[str, Any]]) -> None:
        try:
            with self._input_lock:
                self._input_send_seq += 1
                seq = self._input_send_seq
            t0 = time.perf_counter()
            print(
                f"[AB][INPUT][SEND_START] seq={seq} t={t0:.6f} events={len(batch)}",
                flush=True,
            )

            self.session.input_client.send_input(
                payload={
                    "compileId": self.session.compile_id,
                    "events": batch,
                }
            )

            t1 = time.perf_counter()
            print(
                f"[AB][INPUT][SEND_DONE] seq={seq} t={t1:.6f} "
                f"dt_ms={(t1 - t0) * 1000:.2f}",
                flush=True,
            )

        except Exception as exc:
            print(f"[AB][INPUT][SEND_ERROR] {exc}", file=sys.stderr, flush=True)




    def _input_flush_worker(self) -> None:
        interval = 1.0 / self.input_hz if self.input_hz > 0 else 0.01

        while self._running:
            started = time.time()

            with self._input_lock:
                batch = list(self._input_buffer.values())
                self._input_buffer.clear()
 

            if batch:
                threading.Thread(
                    target=self._send_input_batch_async,
                    args=(batch,),
                    daemon=True,
                    name=f"ABInputSend:{self.session.compile_id}",
                ).start()

            elapsed = time.time() - started
            time.sleep(max(0.0, interval - elapsed))


    @staticmethod
    def _normalize_reward_payload(payload: Any) -> RewardPayload:
        if isinstance(payload, RewardPayload):
            return payload

        if isinstance(payload, Mapping):
            return RewardPayload(
                global_reward=payload.get("global"),
                global_drive=payload.get("global_drive"),
                local_rewards=dict(payload.get("local") or {}),
                local_drives=dict(payload.get("drive") or {}),
                meta=payload.get("meta"),
            )

        raise TypeError(
            "reward_provider must return None, RewardPayload, or a mapping "
            "with keys: global, local, meta"
        )
    
    def _handle_command(self, command: Any) -> None:
        self._update_exploration_from_command(command)

        if self._user_command_executor is not None:
            self._user_command_executor(command)

    def _update_exploration_from_command(self, command: Any) -> None:
        if not self.exploratory_rewards or self._exploration_complete:
            return

        deltas = {}
        if isinstance(command, Mapping):
            maybe_deltas = command.get("deltas")
            if isinstance(maybe_deltas, Mapping):
                deltas = maybe_deltas

        if not deltas:
            return

        total = max(1, len(self.session.output_map.by_output_id))
        if total <= 0:
            return

        active = sum(
            1
            for value in deltas.values()
            if abs(float(value)) >= self.exploratory_min_abs_delta
        )

        ratio = active / float(total)

        if ratio >= self.exploratory_output_ratio:
            self._exploration_complete = True
            print(
                "[AB][EXPLORATION] complete",
                {
                    "active": active,
                    "total": total,
                    "ratio": ratio,
                },
                flush=True,
            )

    def _apply_exploratory_reward_gate(self, reward: RewardPayload) -> RewardPayload:
        if not self.exploratory_rewards or self._exploration_complete:
            return reward

        local_rewards = {
            str(k): 1.0
            for k in reward.local_rewards.keys()
        }

        meta = dict(reward.meta or {})
        meta["exploratory_rewards"] = True
        meta["exploration_complete"] = False

        return RewardPayload(
            global_reward=1.0 if reward.global_reward is not None else None,
            global_drive=1.0,
            local_rewards=local_rewards,
            local_drives={
                str(k): 1.0
                for k in reward.local_rewards.keys()
            },
            meta=meta,
        )