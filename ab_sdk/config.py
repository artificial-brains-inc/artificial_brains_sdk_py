from __future__ import annotations

import os
import httpx
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

def hydrate_env_from_webots_temp_token() -> None:
    project_id = os.getenv("AB_PROJECT_ID")
    temp_token = os.getenv("AB_TEMP_TOKEN")
    node_url = os.getenv("AB_NODE_URL")

    if not project_id or not temp_token:
        return

    if os.getenv("AB_API_KEY") and os.getenv("AB_PYTHON_URL"):
        return

    if not node_url:
        node_url = "https://app.artificialbrains.ai/api"
        os.environ.setdefault("AB_NODE_URL", node_url)

    url = (
        node_url.rstrip("/")
        + f"/robots/webots/{project_id}/get-credentials"
    )

    resp = httpx.post(
        url,
        json={
            "projectId": project_id,
            "tempToken": temp_token,
        },
        headers={
            "x-temp-token": temp_token,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    payload = resp.json()

    credentials = payload.get("credentials") or {}

    for key, value in credentials.items():
        if value is not None:
            os.environ[key] = str(value)


@dataclass
class SDKConfig:
    project_id: str
    python_url: str
    api_key: str
    node_url: Optional[str] = None
    telemetry: bool = True
    timeout: float = 10.0
    output_poll_interval: float = 0.05
    output_limit: int = 100

    @classmethod
    def from_env(
        cls,
        *,
        env_path: str | Path | None = None,
        telemetry: Optional[bool] = None,
        timeout: Optional[float] = None,
        output_poll_interval: Optional[float] = None,
        output_limit: Optional[int] = None,
    ) -> "SDKConfig":
        if env_path is not None:
            load_env_file(Path(env_path))

        hydrate_env_from_webots_temp_token()

        project_id = os.getenv("AB_PROJECT_ID")
        python_url = os.getenv("AB_PYTHON_URL")
        node_url = os.getenv("AB_NODE_URL")
        api_key = os.getenv("AB_API_KEY")

        if telemetry is None:
            telemetry_env = os.getenv("AB_TELEMETRY", "1").strip().lower()
            telemetry = telemetry_env not in {"0", "false", "no", "off"}

        if timeout is None:
            timeout = float(os.getenv("AB_TIMEOUT", "10.0"))

        if output_poll_interval is None:
            output_poll_interval = float(os.getenv("AB_OUTPUT_POLL_INTERVAL", "0.05"))

        if output_limit is None:
            output_limit = int(os.getenv("AB_OUTPUT_LIMIT", "100"))

        if not project_id:
            raise ValueError("Missing AB_PROJECT_ID.")
        if not python_url:
            raise ValueError("Missing AB_PYTHON_URL.")
        if not api_key:
            raise ValueError("Missing AB_API_KEY.")
        if telemetry and not node_url:
            raise ValueError("Missing AB_NODE_URL for telemetry mode.")

        return cls(
            project_id=project_id,
            python_url=python_url,
            node_url=node_url,
            api_key=api_key,
            telemetry=telemetry,
            timeout=timeout,
            output_poll_interval=output_poll_interval,
            output_limit=output_limit,
        )