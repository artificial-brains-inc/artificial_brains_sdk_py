from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class OutputBinding:
    output_id: str
    motor: str
    motor_id: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class OutputMotorMap:
    def __init__(self, entries: Iterable[Dict[str, Any]]) -> None:
        self.by_output_id: Dict[str, OutputBinding] = {}
        self.by_motor: Dict[str, OutputBinding] = {}

        for raw in entries or []:
            output_id = str(raw.get("outputId") or raw.get("output_id") or "").strip()
            motor = str(raw.get("motor") or raw.get("name") or output_id).strip()
            motor_id = raw.get("motorId") or raw.get("motor_id")
            motor_id = str(motor_id) if motor_id is not None else None
            if not output_id:
                raise ValueError("output motor map entry missing outputId")
            if output_id in self.by_output_id:
                raise ValueError(f"duplicate outputId in output motor map: {output_id}")
            if motor in self.by_motor:
                raise ValueError(f"duplicate motor in output motor map: {motor}")
            binding = OutputBinding(output_id=output_id, motor=motor, motor_id=motor_id, meta=dict(raw))
            self.by_output_id[output_id] = binding
            self.by_motor[motor] = binding

    @classmethod
    def from_contract(cls, contract: Dict[str, Any]) -> "OutputMotorMap":
        maps = contract.get("maps") or {}
        mapped = maps.get("output_motor_map")
        if mapped:
            return cls(mapped)

        # Fallback: raw contract["outputs"] shape
        raw_outputs = contract.get("outputs") or []
        entries = []
        for raw in raw_outputs:
            output_id = str(raw.get("id") or raw.get("outputId") or "").strip()
            if output_id:
                entries.append(
                    {
                        "outputId": output_id,
                        "motor": output_id,
                        "meta": dict(raw),
                    }
                )
        return cls(entries)

    def get_by_output_id(self, output_id: str) -> OutputBinding:
        try:
            return self.by_output_id[output_id]
        except KeyError as exc:
            raise KeyError(f"unknown outputId '{output_id}'") from exc
