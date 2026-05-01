# ab_sdk/python_client.py

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import httpx

from . import endpoints


class PythonRealtimeClient:
    def __init__(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        if not base_url:
            raise ValueError("python base_url must be provided")
        self.base_url = base_url.rstrip("/")
        headers: Dict[str, str] = {}
        if project_id:
            headers["x-project-id"] = project_id
        if api_key:
            headers["x-api-key"] = api_key
            headers["Authorization"] = f"Bearer {api_key}"
        self.http = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def compile_direct(
        self,
        *,
        graph: Dict[str, Any],
        compile_id: str,
        signals_token: Optional[str] = None,
        signals: Optional[Dict[str, Any]] = None,
        load_weights: Optional[list[dict[str, Any]]] = None,
        load_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "graph": graph,
            "compileId": compile_id,
            "signals_token": signals_token,
            "signals": signals,
            "load_weights": load_weights,
            "load_state": load_state,
        }
        resp = self.http.post(endpoints.PY_COMPILE, json=payload)
        resp.raise_for_status()
        return resp.json()

    def run_start(self, compile_id: str, **kwargs: Any) -> Dict[str, Any]:
        payload = {"compileId": compile_id, **kwargs}
        resp = self.http.post(endpoints.PY_RUN_START, json=payload)
        resp.raise_for_status()
        return resp.json()

    def run_stop(self, compile_id: str, **kwargs: Any) -> Dict[str, Any]:
        payload = {"compileId": compile_id, **kwargs}
        resp = self.http.post(endpoints.PY_RUN_STOP, json=payload)
        resp.raise_for_status()
        return resp.json()

    def send_input(self, *, payload: Dict[str, Any],) -> Dict[str, Any]:
        resp = self.http.post(endpoints.PY_INPUTS, json=payload)
        resp.raise_for_status()
        return resp.json()

    def send_global_reward(self, *, compile_id: str, value: float, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "compileId": compile_id,
            "scope": "global",
            "value": float(value),
            "meta": meta or {},
        }
        print("[AB][SEND_LOCAL_REWARD]", payload, flush=True)
        resp = self.http.post(endpoints.PY_REWARDS, json=payload)
        resp.raise_for_status()
        return resp.json()

    def send_local_rewards(self, *, compile_id: str, rewards: Dict[str, float], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        results = []
        for target, value in rewards.items():
            payload = {
                "compileId": compile_id,
                "scope": "local",
                "target": str(target),
                "value": float(value),
                "meta": meta or {},
            }
            print("[AB][SEND_LOCAL_REWARDS]", payload, flush=True)
            resp = self.http.post(endpoints.PY_REWARDS, json=payload)
            if resp.status_code >= 400:
                print(
                    "[AB][LOCAL_REWARD_ERROR]",
                    {
                        "status": resp.status_code,
                        "payload": payload,
                        "body": resp.text,
                    },
                    flush=True,
                )
            resp.raise_for_status()
            results.append(resp.json())
        return {"ok": True, "results": results}

    def get_outputs(self, *, compile_id: str, after_step: Optional[int] = None, limit: int = 100) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": limit}
        if after_step is not None:
            params["after_step"] = after_step
        path = endpoints.PY_OUTPUTS.format(compile_id=compile_id)
        resp = self.http.get(path, params=params)
        resp.raise_for_status()
        payload = resp.json()
        print(
            "[AB][GET_OUTPUTS]",
            {
                "base_url": self.base_url,
                "compile_id": compile_id,
                "after_step": after_step,
                "keys": list(payload.keys()),
                "control": payload.get("control"),
            },
            flush=True,
        )
        return payload
    
    def get_weights(self, *, compile_id: str) -> Dict[str, Any]:
        path = endpoints.PY_WEIGHTS.format(compile_id=compile_id)
        resp = self.http.get(path)
        resp.raise_for_status()
        payload = resp.json()
        print(
            "[AB][GET_WEIGHTS]",
            {
                "base_url": self.base_url,
                "compile_id": compile_id,
                "step": payload.get("step"),
                "has_weights": bool(payload.get("weights")),
            },
            flush=True,
        )
        return payload
