from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from . import endpoints


class NodeRealtimeClient:
    def __init__(self, base_url: str, *, api_key: Optional[str] = None, timeout: float = 10.0) -> None:
        if not base_url:
            raise ValueError("node base_url must be provided")
        self.base_url = base_url.rstrip("/")
        headers: Dict[str, str] = {}
        if api_key:
            headers["x-api-key"] = api_key
            headers["Authorization"] = f"Bearer {api_key}"
        self.http = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def initialize(self, project_id: str, **kwargs: Any) -> Dict[str, Any]:
        path = endpoints.NODE_INITIALIZE.format(project_id=project_id)
        resp = self.http.post(path, json={**kwargs})
        return self._json_or_raise(resp, "initialize")

    def start_telemetry(self, project_id: str, compile_id: str) -> Dict[str, Any]:
        path = endpoints.NODE_TELEMETRY_START.format(project_id=project_id)
        resp = self.http.post(path, json={"compileId": compile_id})
        return self._json_or_raise(resp, "start_telemetry")

    def run_stop(self, project_id: str, compile_id: str) -> Dict[str, Any]:
        path = endpoints.NODE_RUN_STOP.format(project_id=project_id)
        resp = self.http.post(path, json={"compileId": compile_id})
        return self._json_or_raise(resp, "run_stop")

    def sdk_run_stopped(self, project_id: str, compile_id: str) -> Dict[str, Any]:
        path = endpoints.NODE_SDK_RUN_STOPPED.format(project_id=project_id)
        resp = self.http.post(path, json={"compileId": compile_id})
        return self._json_or_raise(resp, "sdk_run_stopped")

    def get_session(self, project_id: str, compile_id: str) -> Dict[str, Any]:
        path = endpoints.NODE_SESSION.format(project_id=project_id, compile_id=compile_id)
        resp = self.http.get(path)
        return self._json_or_raise(resp, "get_session")
    
    def claim_webots_credentials(self, project_id: str, temp_token: str) -> Dict[str, Any]:
        path = endpoints.NODE_WEBOTS_CREDENTIALS.format(project_id=project_id)
        resp = self.http.post(
            path,
            json={
                "projectId": project_id,
                "tempToken": temp_token,
            },
            headers={
                "x-temp-token": temp_token,
            },
        )
        return self._json_or_raise(resp, "claim_webots_credentials")

    def checkpoint(self, project_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = endpoints.NODE_CHECKPOINT.format(project_id=project_id)
        print(
            "[AB][NODE][CHECKPOINT] POST",
            {
                "base_url": self.base_url,
                "path": path,
                "compileId": payload.get("compileId"),
                "step": payload.get("step"),
            },
            flush=True,
        )
        resp = self.http.post(path, json=payload, timeout=60.0)
        print(
            "[AB][NODE][CHECKPOINT] RESPONSE",
            {
                "status": resp.status_code,
                "body": resp.text[:500],
            },
            flush=True,
        )
        return self._json_or_raise(resp, "checkpoint")


    @staticmethod
    def _json_or_raise(resp: httpx.Response, op: str) -> Dict[str, Any]:
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Node {op} failed: status={resp.status_code}, body={resp.text}"
            ) from exc
        return resp.json()