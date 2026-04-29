from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class InputBinding:
    input_id: str
    sensor: str
    kind: str
    n: Optional[int] = None
    meta: Optional[Dict[str, Any]] = None


class InputSensorMap:
    """Ready-to-use lookup map built from the contract.

    The controller/backend owns semantic interpretation. The SDK only validates,
    indexes, and normalizes the map so encoders and publishers can use it.
    """

    def __init__(self, entries: Iterable[Dict[str, Any]]) -> None:
        self.by_input_id: Dict[str, InputBinding] = {}
        self.by_sensor: Dict[str, InputBinding] = {}

        for raw in entries or []:
            input_id = str(raw.get("inputId") or raw.get("input_id") or "").strip()
            sensor = str(raw.get("sensor") or raw.get("name") or input_id).strip()
            kind = str(raw.get("kind") or "Unknown").strip()
            n = raw.get("n")
            n = int(n) if n is not None else None
            if not input_id:
                raise ValueError("input sensor map entry missing inputId")
            if input_id in self.by_input_id:
                raise ValueError(f"duplicate inputId in input sensor map: {input_id}")
            if sensor in self.by_sensor:
                raise ValueError(f"duplicate sensor in input sensor map: {sensor}")
            binding = InputBinding(input_id=input_id, sensor=sensor, kind=kind, n=n, meta=dict(raw))
            self.by_input_id[input_id] = binding
            self.by_sensor[sensor] = binding

    @classmethod
    def from_contract(cls, contract: Dict[str, Any]) -> "InputSensorMap":
        maps = contract.get("maps") or {}
        mapped = maps.get("input_sensor_map")
        if mapped:
            return cls(mapped)

        # Fallback: raw contract["inputs"] shape
        raw_inputs = contract.get("inputs") or []
        entries = []
        for raw in raw_inputs:
            input_id = str(raw.get("id") or raw.get("inputId") or "").strip()
            kind = str(raw.get("kind") or "Unknown").strip()
            n = raw.get("n")

            # For raw contracts, use the input id itself as the sensor name.
            # Example: ps0, ps1, gs0, fb_lwm
            sensor = input_id

            if input_id:
                entries.append(
                    {
                        "inputId": input_id,
                        "sensor": sensor,
                        "kind": kind,
                        "n": n,
                        "meta": dict(raw),
                    }
                )

        return cls(entries)


    def get_by_sensor(self, sensor: str) -> InputBinding:
        try:
            return self.by_sensor[sensor]
        except KeyError as exc:
            raise KeyError(f"unknown sensor '{sensor}'") from exc

    def get_by_input_id(self, input_id: str) -> InputBinding:
        try:
            return self.by_input_id[input_id]
        except KeyError as exc:
            raise KeyError(f"unknown inputId '{input_id}'") from exc
