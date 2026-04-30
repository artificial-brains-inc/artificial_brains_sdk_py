# ab_sdk/client.py

from __future__ import annotations

import json
import os
from pathlib import Path

import secrets
from typing import Any, Dict, Optional

from .config import SDKConfig
from .node_client import NodeRealtimeClient
from .python_client import PythonRealtimeClient
from .session import RealtimeSession, SessionConfig


class ABClient:
    """Artificial Brains realtime SDK.

    Main intent:
    - the SDK owns config, auth, transport, session lifecycle, and brain comms
    - the controller owns robot logic only: collect inputs, apply outputs, compute rewards

    Typical usage:

        client = ABClient.from_env(env_path=".env")
        session = client.start_from_env(env_path=".env")
        session.publish_input("camera", frame_vec)
        session.send_global_reward(1.0)
        session.stop()

    Two modes are supported:
    - brokered / telemetry mode: initialize via Node, run via Python, Node telemetry enabled
    - direct mode: compile + run via Python only
    """

    def __init__(
        self,
        *,
        node_url: Optional[str] = None,
        python_url: str,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
        output_poll_interval: float = 0.05,
        output_limit: int = 100,
    ) -> None:
        api_key = api_key or os.getenv("AB_API_KEY")
        if not api_key:
            raise ValueError("ABClient requires an API key. Pass api_key or set AB_API_KEY.")

        self.node = NodeRealtimeClient(node_url, api_key=api_key, timeout=timeout) if node_url else None
        self.python = PythonRealtimeClient(python_url, api_key=api_key, timeout=timeout)
        self.output_poll_interval = output_poll_interval
        self.output_limit = output_limit

    @classmethod
    def from_config(cls, config: SDKConfig) -> "ABClient":
        return cls(
            node_url=config.node_url if config.telemetry else None,
            python_url=config.python_url,
            api_key=config.api_key,
            timeout=config.timeout,
            output_poll_interval=config.output_poll_interval,
            output_limit=config.output_limit,
        )

    @classmethod
    def from_env(
        cls,
        *,
        env_path: str | None = None,
        telemetry: Optional[bool] = None,
        timeout: Optional[float] = None,
        output_poll_interval: Optional[float] = None,
        output_limit: Optional[int] = None,
    ) -> "ABClient":
        config = SDKConfig.from_env(
            env_path=env_path,
            telemetry=telemetry,
            timeout=timeout,
            output_poll_interval=output_poll_interval,
            output_limit=output_limit,
        )
        return cls.from_config(config)


    def _write_initialize_debug_artifacts(
        self,
        *,
        project_id: str,
        init_payload: Dict[str, Any],
    ) -> None:
        debug_dir = Path(os.getenv("AB_DEBUG_DIR", ".ab_debug"))
        debug_dir.mkdir(parents=True, exist_ok=True)

        # single file, always overwritten
        path = debug_dir / f"{project_id}_latest.json"

        path.write_text(json.dumps(init_payload, indent=2, sort_keys=True, default=str))

        print(f"[AB] wrote debug payload: {path}")

        contract = init_payload.get("contract") or {}
        inputs = contract.get("inputs") or []
        outputs = contract.get("outputs") or []

        print(f"[AB] inputs: {[x.get('id') for x in inputs]}")
        print(f"[AB] outputs: {[x.get('id') for x in outputs]}")


    def start(
        self,
        *,
        project_id: str,
        telemetry: bool = True,
        initialize_kwargs: Optional[Dict[str, Any]] = None,
        run_kwargs: Optional[Dict[str, Any]] = None,
    ) -> RealtimeSession:
        if telemetry and not self.node:
            raise ValueError("node_url is required for telemetry mode")

        initialize_kwargs = dict(initialize_kwargs or {})
        run_kwargs = dict(run_kwargs or {})

        if telemetry:
            init_payload = self.node.initialize(project_id, **initialize_kwargs)
            compile_id = init_payload["compileId"]
            contract = init_payload["contract"]
            self._write_initialize_debug_artifacts(
                project_id=project_id,
                init_payload=init_payload,
            )

            python_url = init_payload.get("pythonUrl")
            if not python_url:
                port = init_payload["port"]
                python_url = f"http://127.0.0.1:{port}"

            self.python = PythonRealtimeClient(
                python_url,
                api_key=os.getenv("AB_API_KEY"),
                timeout=10.0,
            )


            run_resp = self.python.run_start(compile_id, **run_kwargs)
            if not run_resp.get("ok", True):
                raise RuntimeError("python run/start failed")

            self.node.start_telemetry(project_id, compile_id)
        else:
            raise ValueError("For direct mode, use start_direct().")

        session = RealtimeSession(
            project_id=project_id,
            compile_id=compile_id,
            contract=contract,
            node_client=self.node,
            python_client=self.python,
            config=SessionConfig(
                telemetry=telemetry,
                poll_interval=self.output_poll_interval,
                output_limit=self.output_limit,
                checkpoint_every_ticks=250,
            ),
        )
        session.start_output_stream()
        return session

    def start_from_config(
        self,
        config: SDKConfig,
        *,
        initialize_kwargs: Optional[Dict[str, Any]] = None,
        run_kwargs: Optional[Dict[str, Any]] = None,
    ) -> RealtimeSession:
        return self.start(
            project_id=config.project_id,
            telemetry=config.telemetry,
            initialize_kwargs=initialize_kwargs,
            run_kwargs=run_kwargs,
        )

    def start_from_env(
        self,
        *,
        env_path: str | None = None,
        telemetry: Optional[bool] = None,
        timeout: Optional[float] = None,
        output_poll_interval: Optional[float] = None,
        output_limit: Optional[int] = None,
        initialize_kwargs: Optional[Dict[str, Any]] = None,
        run_kwargs: Optional[Dict[str, Any]] = None,
    ) -> RealtimeSession:
        config = SDKConfig.from_env(
            env_path=env_path,
            telemetry=telemetry,
            timeout=timeout,
            output_poll_interval=output_poll_interval,
            output_limit=output_limit,
        )
        return self.start_from_config(
            config,
            initialize_kwargs=initialize_kwargs,
            run_kwargs=run_kwargs,
        )

    def start_direct(
        self,
        *,
        graph: Dict[str, Any],
        contract: Dict[str, Any],
        compile_id: Optional[str] = None,
        signals_token: Optional[str] = None,
        signals: Optional[Dict[str, Any]] = None,
        load_weights: Optional[list[dict[str, Any]]] = None,
        load_state: Optional[Dict[str, Any]] = None,
        run_kwargs: Optional[Dict[str, Any]] = None,
    ) -> RealtimeSession:
        run_kwargs = dict(run_kwargs or {})
        compile_id = compile_id or f"compile_{secrets.token_hex(8)}"

        compile_resp = self.python.compile_direct(
            graph=graph,
            compile_id=compile_id,
            signals_token=signals_token,
            signals=signals,
            load_weights=load_weights,
            load_state=load_state,
        )
        if not compile_resp.get("ok") or not compile_resp.get("compiled"):
            raise RuntimeError("python compile failed")

        run_resp = self.python.run_start(compile_id, **run_kwargs)
        if not run_resp.get("ok", True):
            raise RuntimeError("python run/start failed")

        session = RealtimeSession(
            project_id=None,
            compile_id=compile_id,
            contract=contract,
            node_client=None,
            python_client=self.python,
            config=SessionConfig(
                telemetry=False,
                poll_interval=self.output_poll_interval,
                output_limit=self.output_limit,
            ),
        )
        session.start_output_stream()
        return session