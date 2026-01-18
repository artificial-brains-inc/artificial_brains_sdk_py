"""
ab_sdk/plugins/decoder.py

Generic spike decoders: streamed output spikes -> actuator deltas.

You provide:
- outputs: a list of rows like {"t": 190, "id": "V2", "bits": [0,1,0,...]} sent by the brain
- mapping: how each output population maps to an actuator channel
- scheme: how spikes become a scalar control signal

This module is robot-agnostic.
It does NOT assume a fixed number of joints, a gripper, or a specific robot.
It simply returns "deltas per timestep", keyed by channel name.

---------------------------------------------------------------------------
Output format (from server)
---------------------------------------------------------------------------

The brain streams output activity as a list of rows like:

    {"t": 190, "id": "V2", "bits": [0,1,0,...]}

- t: timestep
- id: output population name
- bits: 0/1 spikes for that population at that timestep

---------------------------------------------------------------------------
Mapping format (what you provide)
---------------------------------------------------------------------------

Each mapping entry connects an output population (row["id"]) to a channel name.
Channel names are arbitrary strings you choose (e.g. "joint:0", "wheel:left", "thruster:z") based on your robot/sim controller.

Minimum fields per entry:

    {
      "node_id": "V2",            # matches row["id"]
      "channel": "joint:3",       # any string identifier for your actuator
      "scheme": "bipolarSplit",   # see schemes below
      "per_step_max": 0.003,      # max delta per timestep (units = your choice)
      "gain": 0.5                 # scale
    }

Optional:
- deadzone: float
- min_step: float
- invert: bool
- threshold: int (required only for booleanThreshold)
- clamp: (min,max) post-scale clamp

If multiple entries target the same channel, their deltas are added.

---------------------------------------------------------------------------
Schemes (bits -> scalar)
---------------------------------------------------------------------------

1) "bipolarSplit"
   value = (sum(first_half) - sum(second_half))

2) "addition"
   value = sum(bits)

3) "booleanThreshold"
   value = 1.0 if sum(bits) >= threshold else 0.0
   Range {0, 1}

4) "bipolarScalar"
   value = +1.0 if first_half wins
           -1.0 if second_half wins
            0.0 if tie
   Range {-1, 0, +1}

After value is computed:
    delta = value * per_step_max * gain
Then we apply optional deadzone/min_step/invert/clamp.

---------------------------------------------------------------------------
What you get back
---------------------------------------------------------------------------

A list of commands ordered by timestep:

    [
      {"t": 188, "deltas": {"joint:0": 0.001, "joint:3": -0.0004}},
      {"t": 189, "deltas": {"joint:0": 0.0,   "joint:3":  0.0002}},
      ...
    ]

Your robot controller applies those deltas to its actuators however it wants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

OutputRow = Dict[str, Any]
Command = Dict[str, Any]


@dataclass
class MappingEntry:
    node_id: str
    channel: str
    scheme: str = "bipolarSplit"  # bipolarSplit | addition | booleanThreshold | bipolarScalar
    per_step_max: float = 0.01
    gain: float = 1.0
    deadzone: float = 0.0
    min_step: float = 0.0
    invert: bool = False
    threshold: Optional[int] = None                 # for booleanThreshold
    clamp: Optional[Tuple[float, float]] = None     # optional post-scale clamp


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _as_bits(bits: Any) -> Optional[List[int]]:
    if not isinstance(bits, list):
        return None
    out: List[int] = []
    for b in bits:
        try:
            out.append(1 if int(b) else 0)
        except Exception:
            out.append(0)
    return out


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
    return pos - neg


def _addition(bits: List[int]) -> float:
    n = len(bits)
    if n <= 0:
        return 0.0
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

        node_id = str(m.get("node_id") or m.get("nodeId") or "")
        channel = str(m.get("channel") or m.get("controllerChannel") or "")
        if not node_id or not channel:
            # channel is required for generic robots
            continue

        clamp_val = m.get("clamp") or m.get("limits")  # allow "limits" synonym
        clamp_tuple: Optional[Tuple[float, float]] = None
        if isinstance(clamp_val, dict) and "min" in clamp_val and "max" in clamp_val:
            clamp_tuple = (float(clamp_val["min"]), float(clamp_val["max"]))
        elif isinstance(clamp_val, (list, tuple)) and len(clamp_val) == 2:
            clamp_tuple = (float(clamp_val[0]), float(clamp_val[1]))

        out.append(
            MappingEntry(
                node_id=node_id,
                channel=channel,
                scheme=str(m.get("scheme") or "bipolarSplit"),
                per_step_max=float(
                    m.get("per_step_max")
                    if m.get("per_step_max") is not None
                    else m.get("perStepMax", m.get("perStepMaxRad", 0.01))
                ),
                gain=float(m.get("gain", 1.0)),
                deadzone=float(m.get("deadzone", 0.0)),
                min_step=float(m.get("min_step") if m.get("min_step") is not None else m.get("minStep", m.get("minStepRad", 0.0))),
                invert=bool(m.get("invert", False)),
                threshold=(int(m["threshold"]) if m.get("threshold") is not None else None),
                clamp=clamp_tuple,
            )
        )
    return out


def decode_stream_rows(
    rows: List[OutputRow],
    mapping: Iterable[Union[MappingEntry, Dict[str, Any]]],
) -> List[Command]:
    """
    Convert streamed output rows into per-timestep actuator deltas.

    Returns:
        [
          {"t": 188, "deltas": {"joint:0": 0.0012, "wheel:left": 0.0}},
          {"t": 189, "deltas": {...}},
        ]
    """
    mp = normalize_mapping(mapping)

    # node_id -> mapping entries
    by_id: Dict[str, List[MappingEntry]] = {}
    for e in mp:
        by_id.setdefault(e.node_id, []).append(e)

    # group by timestep (t is source of truth)
    by_t: Dict[int, List[OutputRow]] = {}
    for r in rows or []:
        try:
            t = int(r.get("t"))
        except Exception:
            continue
        by_t.setdefault(t, []).append(r)

    out_cmds: List[Command] = []
    for t in sorted(by_t.keys()):
        deltas: Dict[str, float] = {}

        for r in by_t[t]:
            out_id = str(r.get("id") or "")
            if not out_id:
                continue
            entries = by_id.get(out_id)
            if not entries:
                continue

            bits = _as_bits(r.get("bits"))
            if bits is None:
                continue

            for entry in entries:
                value = _compute_value(bits, entry)
                delta = _value_to_delta(value, entry)
                if delta == 0.0:
                    continue
                deltas[entry.channel] = deltas.get(entry.channel, 0.0) + delta

        out_cmds.append({"t": t, "deltas": deltas})

    return out_cmds


# Optional convenience: turn channel deltas into dq/dg if your robot uses that pattern
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
