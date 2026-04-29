# ab_sdk/decoder.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
import re

OutputEvent = Dict[str, Any]
Command = Dict[str, Any]


@dataclass
class MappingEntry:
    output_id: str
    channel: str
    scheme: str = "bipolarSplit"   # bipolarSplit | addition | booleanThreshold | bipolarScalar
    per_step_max: float = 0.01
    gain: float = 1.0
    deadzone: float = 0.0
    min_step: float = 0.0
    invert: bool = False
    threshold: Optional[int] = None
    clamp: Optional[Tuple[float, float]] = None
    n: Optional[int] = None


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


# ----------------------------
# Schemes: bits -> scalar
# ----------------------------

def _bipolar_split(bits: List[int]) -> float:
    n = len(bits)
    if n < 2:
        return 0.0
    half = n // 2
    if half <= 0:
        return 0.0
    pos = sum(bits[:half])
    neg = sum(bits[half:half * 2])
    return float(pos - neg)


def _addition(bits: List[int]) -> float:
    return float(sum(bits))


def _boolean_threshold(bits: List[int], threshold: int) -> float:
    n = len(bits)
    if n <= 0:
        return 0.0
    thr = int(threshold)
    if thr < 1:
        thr = 1
    if thr > n:
        thr = n
    return 1.0 if sum(bits) >= thr else 0.0


def _bipolar_scalar(bits: List[int]) -> float:
    n = len(bits)
    if n < 2:
        return 0.0
    half = n // 2
    if half <= 0:
        return 0.0
    pos = sum(bits[:half])
    neg = sum(bits[half:half * 2])
    if pos > neg:
        return 1.0
    if neg > pos:
        return -1.0
    return 0.0


def _compute_value(bits: List[int], entry: MappingEntry) -> float:
    scheme = (entry.scheme or "bipolarSplit").strip()

    if scheme == "bipolarSplit":
        return _bipolar_split(bits)

    if scheme == "addition":
        return _addition(bits)

    if scheme == "booleanThreshold":
        thr = entry.threshold
        if thr is None:
            thr = max(1, len(bits) // 2)
        return _boolean_threshold(bits, int(thr))

    if scheme == "bipolarScalar":
        return _bipolar_scalar(bits)

    return 0.0


def _value_to_delta(value: float, entry: MappingEntry) -> float:
    if entry.invert:
        value = -value

    delta = float(value) * float(entry.per_step_max) * float(entry.gain)

    if entry.deadzone and abs(delta) < float(entry.deadzone):
        return 0.0

    if entry.min_step and 0.0 < abs(delta) < float(entry.min_step):
        delta = float(entry.min_step) if delta > 0 else -float(entry.min_step)

    if entry.clamp is not None and isinstance(entry.clamp, (tuple, list)) and len(entry.clamp) == 2:
        lo, hi = float(entry.clamp[0]), float(entry.clamp[1])
        delta = _clamp(delta, lo, hi)

    return delta


def normalize_mapping(mapping: Iterable[Union[MappingEntry, Dict[str, Any]]]) -> List[MappingEntry]:
    out: List[MappingEntry] = []

    for m in mapping:
        if isinstance(m, MappingEntry):
            out.append(m)
            continue

        if not isinstance(m, dict):
            continue

        output_id = str(
            m.get("output_id")
            or m.get("outputId")
            or m.get("node_id")
            or m.get("nodeId")
            or ""
        )
        channel = str(m.get("channel") or m.get("controllerChannel") or "")
        if not output_id or not channel:
            continue

        clamp_val = m.get("clamp") or m.get("limits")
        clamp_tuple: Optional[Tuple[float, float]] = None
        if isinstance(clamp_val, dict) and "min" in clamp_val and "max" in clamp_val:
            clamp_tuple = (float(clamp_val["min"]), float(clamp_val["max"]))
        elif isinstance(clamp_val, (list, tuple)) and len(clamp_val) == 2:
            clamp_tuple = (float(clamp_val[0]), float(clamp_val[1]))

        out.append(
            MappingEntry(
                output_id=output_id,
                channel=channel,
                scheme=str(m.get("scheme") or "bipolarSplit"),
                per_step_max=float(
                    m.get("per_step_max")
                    if m.get("per_step_max") is not None
                    else m.get("perStepMax", m.get("perStepMaxRad", 0.01))
                ),
                gain=float(m.get("gain", 1.0)),
                deadzone=float(m.get("deadzone", 0.0)),
                min_step=float(
                    m.get("min_step")
                    if m.get("min_step") is not None
                    else m.get("minStep", m.get("minStepRad", 0.0))
                ),
                invert=bool(m.get("invert", False)),
                threshold=(int(m["threshold"]) if m.get("threshold") is not None else None),
                clamp=clamp_tuple,
                n=(int(m["n"]) if m.get("n") is not None else None),
            )
        )

    return out


_NEURON_ID_RX = re.compile(r"^([^:]+):(\d+)$")


def _extract_bits_by_output(output_event: OutputEvent, mapping: List[MappingEntry]) -> Dict[str, List[int]]:
    """
    Rebuild dense bits from runtime sparse spike events.

    output_event shape:
        {
            "step": int,
            "outputs": [
                {"t": int, "neurons": ["left_wheel_motor:0", "left_wheel_motor:5", ...]},
                ...
            ],
            "telemetry": {...}
        }
    """
    configured_n: Dict[str, int] = {}
    for entry in mapping:
        if entry.n is not None and entry.n > 0:
            configured_n[entry.output_id] = max(configured_n.get(entry.output_id, 0), int(entry.n))

    active_by_output: Dict[str, set[int]] = {}

    seq = output_event.get("outputs")
    if isinstance(seq, list):
        for item in seq:
            if not isinstance(item, dict):
                continue

            neurons = item.get("neurons")
            if not isinstance(neurons, list):
                continue

            for nid in neurons:
                if not isinstance(nid, str):
                    continue

                m = _NEURON_ID_RX.match(nid.strip())
                if not m:
                    continue

                output_id = m.group(1)
                idx = int(m.group(2))
                if idx < 0:
                    continue

                bucket = active_by_output.setdefault(output_id, set())
                bucket.add(idx)

                if output_id not in configured_n or idx + 1 > configured_n[output_id]:
                    configured_n[output_id] = idx + 1

    bits_by_output: Dict[str, List[int]] = {}

    for output_id, width in configured_n.items():
        if width <= 0:
            continue
        bits = [0] * width
        for idx in active_by_output.get(output_id, set()):
            if 0 <= idx < width:
                bits[idx] = 1
        bits_by_output[output_id] = bits

    return bits_by_output


class GenericSpikeDecoder:
    """
    Generic SDK decoder.

    Input:
        one runtime output_event

    Output:
        {
            "t": step,
            "deltas": {
                "<channel>": float,
                ...
            }
        }
    """

    def __init__(self, mapping: Iterable[Union[MappingEntry, Dict[str, Any]]]) -> None:
        self.mapping = normalize_mapping(mapping)

    def decode(self, output_event: Dict[str, Any], context: Dict[str, Any]) -> Command:
        step = int(output_event.get("step", -1))
        bits_by_output = _extract_bits_by_output(output_event, self.mapping)

        deltas: Dict[str, float] = {}

        for entry in self.mapping:
            bits = bits_by_output.get(entry.output_id)
            if bits is None:
                continue

            value = _compute_value(bits, entry)
            delta = _value_to_delta(value, entry)
            if delta == 0.0:
                continue

            deltas[entry.channel] = deltas.get(entry.channel, 0.0) + delta

        return {
            "t": step,
            "deltas": deltas,
        }


def deltas_to_dq_dg(deltas: Dict[str, float], *, dof: int, joint_prefix: str = "joint:") -> Dict[str, Any]:
    dq = [0.0] * int(dof)
    dg = 0.0
    for k, v in deltas.items():
        if k.startswith(joint_prefix):
            try:
                idx = int(k.split(":", 1)[1])
                if 0 <= idx < len(dq):
                    dq[idx] += float(v)
            except Exception:
                continue
        elif k == "dg" or k == "gripper":
            dg += float(v)
    return {"dq": dq, "dg": dg}