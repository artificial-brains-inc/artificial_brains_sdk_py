"""HTTP and realtime client for ArtificialBrains.

This module defines the :class:`ABClient` class which wraps the REST
endpoints exposed by the Artificial Brains server and manages the
underlying realtime (Socket.IO) connection.  It is responsible for
starting and stopping runs, querying the current input state and
creating :class:`~ab_sdk.run_session.RunSession` instances which
encapsulate per‑run state and socket clients.  You should not need to
deal with low level HTTP or Socket.IO interactions outside of this
class.

Usage example::

    from ab_sdk import ABClient

    client = ABClient("https://app.artificialbrains.ai/api", api_key="your_key")
    run = client.start("my_project")
    # ... attach sensors, run loop ...
    client.stop("my_project")

The `start` method returns a :class:`~ab_sdk.run_session.RunSession` object
containing the run contract (IO manifest, constants) and a Socket.IO
client already joined to the run room.  See the documentation on
`RunSession` for details.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import httpx
import socketio

from .run_session import RunSession
from . import endpoints
from .contract_scaffold import sync_policies_from_contract

logger = logging.getLogger(__name__)


class ABClient:
    """Client for interacting with the Artificial Brains backend.

    Auth:
      - This SDK always sends your machine API key on *every* HTTP request using:
          * `x-api-key: <key>`  (preferred by the server)
        and also:
          * `Authorization: Bearer <key>` (accepted by the server as a fallback)

    Base URL:
      - Provide either:
          * https://app.artificialbrains.ai/api
        If you pass a host without `/api`, the client will append `/api` automatically.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
        socket_namespace: str = "/ab",
    ) -> None:
        if not base_url:
            raise ValueError("base_url must be provided")

        base = base_url.rstrip("/")
        # Accept either host root or /api, but store a base_url that ends with /api.
        if not base.endswith("/api"):
            base = base + "/api"

        self.base_url = base
        self.api_key = api_key or None
        self.timeout = timeout
        self.socket_namespace = socket_namespace

        headers: Dict[str, str] = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"

        # httpx base_url joins *relative* paths; leading '/' would reset the path.
        self._http = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)
        logger.debug("ABClient initialized with base_url=%s", self.base_url)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Internal helper for sending HTTP requests."""
        url = path.lstrip("/")  # preserve /api prefix in base_url
        try:
            response = self._http.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP error: %s", exc)
            raise
        except httpx.RequestError as exc:
            logger.error("Request failed: %s", exc)
            raise

    def start(self, project_id: str, **kwargs: Any) -> RunSession:
        """Start a new run and connect to realtime."""
        if not project_id:
            raise ValueError("project_id must be provided")

        path = endpoints.START_RUN.format(project_id=project_id)
        logger.info("Starting run for project %s", project_id)
        response = self._request("POST", path, json=kwargs or {})
        contract = response.json()

        run_id = contract.get("runId")
        if not run_id:
            raise ValueError("start response missing 'runId'")

        # Determine Socket.IO connection details
        rt_info = contract.get("realtime", {}) or {}
        ns = rt_info.get("namespace", self.socket_namespace)
        url = rt_info.get("url")

        if not url:
            # derive host root from base_url (/api stripped)
            url = self.base_url[:-4] if self.base_url.endswith("/api") else self.base_url

        socket = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,  # infinite retries
            reconnection_delay=1,
            reconnection_delay_max=5,
            logger=False,              # Enable to see ping/pong
            engineio_logger=False,
            request_timeout=3600,      # Allow long requests (1 hour)
        )

        connect_headers: Dict[str, str] = {}
        auth_payload: Optional[Dict[str, Any]] = None
        if self.api_key:
            connect_headers["x-api-key"] = self.api_key
            connect_headers["Authorization"] = f"Bearer {self.api_key}"
            # Some server middleware reads handshake.auth
            auth_payload = {"token": self.api_key, "apiKey": self.api_key}

        logger.info("Connecting to realtime at %s namespace %s", url, ns)
         # Helpful visibility: log namespace connect/disconnect
        @socket.on("connect", namespace=ns)
        def _on_connect():
            logger.info("Realtime connected to namespace %s", ns)

        @socket.on("disconnect", namespace=ns)
        def _on_disconnect():
            logger.warning("Realtime disconnected from namespace %s", ns)

        # Use polling + websocket (not websocket-only)
        # This maintains connection through NAT devices
        socket.connect(
            url,
            headers=connect_headers,
            auth=auth_payload,
            namespaces=[ns],
            transports=["websocket"],
            wait=True,
            wait_timeout=120,
        )
            

        # HARD ASSERT: the namespace must actually be connected, or emits will fail with:
        # "/ab is not a connected namespace."
        namespaces = getattr(socket, "namespaces", {}) or {}
        if ns not in namespaces:
            try:
                socket.disconnect()
            except Exception:
                pass
            raise socketio.exceptions.ConnectionError(
                f"Socket connected but namespace '{ns}' is NOT connected. Connected namespaces: {list(namespaces.keys())}"
            )
        
        # Join run
        socket.emit(endpoints.RUN_JOIN_EVENT, {"runId": run_id}, namespace=ns)

        return RunSession(
            client=self,
            project_id=project_id,
            run_id=run_id,
            contract=contract,
            socket=socket,
            namespace=ns,
        )

    def stop(self, project_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Stops a run on the server.

        NOTE: Your server's stop endpoint expects a body with { runId }.
        If run_id is not provided, server may not stop anything.
        """
        if not project_id:
            raise ValueError("project_id must be provided")

        path = endpoints.STOP_RUN.format(project_id=project_id)
        payload: Dict[str, Any] = {}
        if run_id:
            payload["runId"] = run_id

        logger.info("Stopping run for project %s runId=%s", project_id, run_id)
        response = self._request("POST", path, json=payload)
        return response.json()

    def get_io_state(self, project_id: str) -> Dict[str, Any]:
        if not project_id:
            raise ValueError("project_id must be provided")
        path = endpoints.IO_STATE.format(project_id=project_id)
        logger.debug("Fetching IO state for project %s", project_id)
        response = self._request("GET", path)
        return response.json()
    
    def get_contract(self, project_id: str) -> Dict[str, Any]:
        """
        Fetch the IO/constants contract without starting a run.

        Requires your server to implement:
          GET /api/robot/:project_id/contract
        returning:
          { ok: true, projectId, constants: {...}, io: {...} }
        """
        if not project_id:
            raise ValueError("project_id must be provided")
        path = endpoints.CONTRACT.format(project_id=project_id)
        logger.debug("Fetching contract for project %s", project_id)
        response = self._request("GET", path)
        return response.json()

    def sync_policies(self, project_id: str, *, policies_dir: str = "policies") -> Dict[str, Any]:
        """
        One command devs can run whenever they want:
          - overwrites machine-owned contract files
          - never overwrites user-owned policy files
        """
        contract = self.get_contract(project_id)
        res = sync_policies_from_contract(contract, policies_dir=policies_dir)
        return {
            "ok": True,
            "policiesDir": res.policies_dir,
            "sha256": res.sha256,
            "createdRewardPolicy": res.created_reward_policy,
            "createdDeviationPolicy": res.created_deviation_policy,
        }


    def close(self) -> None:
        self._http.close()