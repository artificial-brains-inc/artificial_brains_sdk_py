# ab_sdk/session.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .encoder import SpikeEncoder
from .maps import InputSensorMap, OutputMotorMap, RewardMap
from .output_stream import OutputStream


@dataclass
class SessionConfig:
    telemetry: bool = True
    poll_interval: float = 0.05
    output_limit: int = 100


class RealtimeSession:
    def __init__(
        self,
        *,
        project_id: Optional[str],
        compile_id: str,
        contract: Dict[str, Any],
        node_client: Any,
        python_client: Any,
        config: SessionConfig,
    ) -> None:
        self.project_id = project_id
        self.compile_id = compile_id
        self.contract = contract
        self.node_client = node_client
        self.python_client = python_client
        self.config = config

        self.input_map = InputSensorMap.from_contract(contract)
        self.output_map = OutputMotorMap.from_contract(contract)
        self.reward_map = RewardMap.from_contract(contract)
        self.encoder = SpikeEncoder(self.input_map)

        self.decoder: Optional[Any] = None
        self.output_stream = OutputStream(
            python_client,
            compile_id=compile_id,
            poll_interval=config.poll_interval,
            limit=config.output_limit,
        )
        self._output_handlers: list[Callable[[Dict[str, Any]], None]] = []
        self._command_handlers: list[Callable[[Any], None]] = []
        self._control_handlers: list[Callable[[Dict[str, Any]], None]] = []
        self._running = False

        self.output_stream.on_item(self._dispatch_output)
        self.output_stream.on_control(self._dispatch_control)

    def set_decoder(self, decoder: Any) -> None:
        self.decoder = decoder

    def on_output(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        self._output_handlers.append(handler)

    def on_command(self, handler: Callable[[Any], None]) -> None:
        self._command_handlers.append(handler)

    def start_output_stream(self) -> None:
        self.output_stream.start()
        self._running = True

    def publish_input(
        self,
        sensor: str,
        signal: Any,
        *,
        mode: Optional[str] = None,
        vmax: Optional[float] = None,
        vmin: Optional[float] = None,
        absmax: Optional[float] = None,
        radius: int = 1,
        meta: Optional[dict] = None,
    ) -> Dict[str, Any]:
        encoded = self.encoder.encode(
            sensor,
            signal,
            mode=mode,
            vmax=vmax,
            vmin=vmin,
            absmax=absmax,
            radius=radius,
            meta=meta,
        )
        payload = self.encoder.build_input_request(
            compile_id=self.compile_id,
            encoded=encoded,
        )
        return self.python_client.send_input(payload=payload)

    def send_global_reward(self, value: float, *, meta: Optional[dict] = None) -> Dict[str, Any]:
        return self.python_client.send_global_reward(
            compile_id=self.compile_id,
            value=value,
            meta=meta,
        )

    def send_local_reward(self, name: str, value: float, *, meta: Optional[dict] = None) -> Dict[str, Any]:
        return self.send_local_rewards(
            {name: float(value)},
            meta=meta,
        )

    def send_local_rewards(self, rewards: Dict[str, float], *, meta: Optional[dict] = None) -> Dict[str, Any]:
        routed: Dict[str, float] = {}

        for from_output, value in rewards.items():
            bindings = self.reward_map.get_by_output(from_output)

            if not bindings:
                raise KeyError(f"unknown local reward output '{from_output}'")

            for binding in bindings:
               routed[binding.meta["layer"]] = float(value)

        return self.python_client.send_local_rewards(
            compile_id=self.compile_id,
            rewards=routed,
            meta=meta,
        )

    def stop(self, *, notify_node: bool = True) -> None:
        if not self._running:
            return
        self._running = False
        self.python_client.run_stop(self.compile_id)
        self.output_stream.stop()
        if notify_node and self.config.telemetry and self.node_client and self.project_id:
            self.node_client.sdk_run_stopped(self.project_id, self.compile_id)
    
    def close_from_runtime(self, *, notify_node: bool = True) -> None:
        if not self._running:
            return
        self._running = False
        self.output_stream.stop()
        if notify_node and self.config.telemetry and self.node_client and self.project_id:
            self.node_client.sdk_run_stopped(self.project_id, self.compile_id)


    def _dispatch_output(self, item: Dict[str, Any]) -> None:
        for handler in list(self._output_handlers):
            handler(item)

        if self.decoder is None:
            return

        command = self.decoder.decode(
            item,
            context={
                "session": self,
                "contract": self.contract,
            },
        )
        if command is None:
            return
        for handler in list(self._command_handlers):
            handler(command)

    def _dispatch_control(self, control: Dict[str, Any]) -> None:
        print(f"[AB][CONTROL] received {control}")

        for handler in list(self._control_handlers):
            handler(control)

        for handler in list(self._command_handlers):
            handler(control)
    
    def on_control(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        self._control_handlers.append(handler)
