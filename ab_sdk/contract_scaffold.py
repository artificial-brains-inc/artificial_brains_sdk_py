# ab_sdk/contract_scaffold.py
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


MACHINE_OWNED_JSON = "_contract.json"
MACHINE_OWNED_PY = "_contract.py"
MACHINE_OWNED_SHA = "_contract.sha256"

USER_REWARD_POLICY = "reward_policy.py"
USER_DEVIATION_POLICY = "error_deviation_policy.py"


def _stable_contract_view(contract: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strip run-specific fields and keep only what a dev needs to write policies.
    This is what we hash + persist.
    """
    io = (contract or {}).get("io") or {}
    consts = (contract or {}).get("constants") or {}

    # Keep only the things that define the "policy contract"
    view = {
        "constants": {
            "gamma": int(consts.get("gamma", 64)),
            "outputWindowN": int(consts.get("outputWindowN", 32)),
            "feedbackN": int(consts.get("feedbackN", 128)),
            "feedbackT": int(consts.get("feedbackT", consts.get("FEEDBACK_WINDOW_T", 128))),
        },
        "io": {
            "inputs": list(io.get("inputs") or []),
            "outputs": list(io.get("outputs") or []),
            "feedback": list(io.get("feedback") or []),
            "stdp3": {"layers": list(((io.get("stdp3") or {}).get("layers")) or [])},
        },
    }
    return view


def _json_bytes(obj: Any) -> bytes:
    # stable, deterministic serialization
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return s.encode("utf-8")


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _write_bytes(path: str, b: bytes) -> None:
    with open(path, "wb") as f:
        f.write(b)


def _exists(path: str) -> bool:
    try:
        return os.path.exists(path)
    except Exception:
        return False


def _render_contract_py(view: Dict[str, Any], sha256_hex: str) -> str:
    consts = (view.get("constants") or {})
    io = (view.get("io") or {})
    inputs = io.get("inputs") or []
    outputs = io.get("outputs") or []
    feedback = io.get("feedback") or []
    stdp_layers = ((io.get("stdp3") or {}).get("layers")) or []

    input_ids = [str(x.get("id")) for x in inputs if isinstance(x, dict) and x.get("id")]
    output_ids = [str(x.get("id")) for x in outputs if isinstance(x, dict) and x.get("id")]
    feedback_ids = [str(x.get("id")) for x in feedback if isinstance(x, dict) and x.get("id")]

    # Keep a tiny amount of metadata that’s helpful for policy authors
    feedback_meta = []
    for fb in feedback:
        if not isinstance(fb, dict):
            continue
        feedback_meta.append(
            {
                "id": str(fb.get("id")),
                "n": int(fb.get("n", consts.get("feedbackN", 128))),
                "fromOutput": fb.get("fromOutput"),
                "outputKind": fb.get("outputKind"),
            }
        )

    return f'''"""
AUTO-GENERATED FILE. DO NOT EDIT.

This file is machine-owned and overwritten whenever you "sync contract".
It is meant to give developers the IDs they need for:
- per-layer STDP3 reward (by stdp layer id)
- per-feedback deviation (by feedback input id)

If this changes, your graph/IO changed. Compare sha256 or diff _contract.json.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, TypedDict


CONTRACT_SHA256 = "{sha256_hex}"

# Constants (as reported by server)
GAMMA: int = {int(consts.get("gamma", 64))}
OUTPUT_WINDOW_N: int = {int(consts.get("outputWindowN", 32))}
FEEDBACK_N: int = {int(consts.get("feedbackN", 128))}
FEEDBACK_T: int = {int(consts.get("feedbackT", 128))}

# IDs you typically need in policies
INPUT_IDS: List[str] = {input_ids!r}
OUTPUT_IDS: List[str] = {output_ids!r}
FEEDBACK_IDS: List[str] = {feedback_ids!r}

# Per-layer reward keys (STDP3)
STDP3_LAYERS: List[str] = {list(map(str, stdp_layers))!r}


class FeedbackInfo(TypedDict, total=False):
    id: str
    n: int
    fromOutput: Optional[str]
    outputKind: Optional[str]


FEEDBACK_INFO: List[FeedbackInfo] = {feedback_meta!r}
'''


def _render_default_reward_policy() -> str:
    return '''"""
User-owned policy file (created once; never overwritten).

Implement:
  compute_reward(summary, stdp_layers) -> (global_reward, by_layer)

- global_reward: float in [0,1] (or whatever your server expects)
- by_layer: dict mapping STDP3 layer-id -> reward float (same range)

You can import ids from:
  from policies._contract import STDP3_LAYERS

Note: Keep this deterministic. No RNG here unless you *explicitly* want it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List


@dataclass
class CycleSummary:
    # Example fields – you can change these to match your controller summary.
    startDist: Optional[float] = None
    endDist: Optional[float] = None
    success: bool = False


def compute_reward(
    summary: Optional[CycleSummary],
    *,
    stdp_layers: List[str],
) -> Tuple[float, Dict[str, float]]:
    """
    Return (global_reward, by_layer).

    Default behavior:
      - If success: reward = 1.0
      - Else if distance improved: reward = 0.6
      - Else: reward = 0.4

    Change freely.
    """
    if summary is None:
        r = 0.5
    else:
        if summary.success:
            r = 1.0
        elif (summary.startDist is not None and summary.endDist is not None and summary.endDist < summary.startDist):
            r = 0.6
        else:
            r = 0.4

    by_layer = {layer_id: float(r) for layer_id in (stdp_layers or [])}
    return float(r), by_layer
'''


def _render_default_deviation_policy() -> str:
    return '''"""
User-owned policy file (created once; never overwritten).

Goal:
  For EACH feedback input id (fb.id), produce deviation_f32:
    dev: list[float] length T, values typically in [-1,1]
  The server will convert dev into a feedback raster using baseline + your corrections.

You can import ids from:
  from policies._contract import FEEDBACK_IDS, FEEDBACK_INFO

You decide the meaning of dev[t] (closer/farther, torque error, etc).
Keep deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class DeviationContext:
    """
    Put whatever you want here: distances by timestep, joint errors, etc.
    The controller can pass this in when a feedback need arrives.
    """
    # Example:
    dist_by_t: Optional[Dict[int, float]] = None


def compute_deviation(
    feedback_id: str,
    *,
    T: int,
    ctx: Optional[DeviationContext] = None,
) -> List[float]:
    """
    Return dev[t] length T.

    Default is all zeros (no correction).
    Customize per feedback_id if you want different deviation semantics per channel.
    """
    _ = feedback_id
    _ = ctx
    return [0.0] * int(T)
'''


@dataclass
class ScaffoldResult:
    policies_dir: str
    wrote_contract: bool
    created_reward_policy: bool
    created_deviation_policy: bool
    sha256: str


def sync_policies_from_contract(
    contract: Dict[str, Any],
    *,
    policies_dir: str = "policies",
) -> ScaffoldResult:
    """
    - Always overwrites:
        policies/_contract.json
        policies/_contract.py
        policies/_contract.sha256
    - Creates once (never overwrites):
        policies/reward_policy.py
        policies/error_deviation_policy.py
    """
    _ensure_dir(policies_dir)

    view = _stable_contract_view(contract)
    jb = _json_bytes(view)
    sha = _sha256_hex(jb)

    # Machine-owned outputs (always overwritten)
    contract_json_path = os.path.join(policies_dir, MACHINE_OWNED_JSON)
    contract_py_path = os.path.join(policies_dir, MACHINE_OWNED_PY)
    contract_sha_path = os.path.join(policies_dir, MACHINE_OWNED_SHA)

    _write_text(contract_json_path, json.dumps(view, indent=2, ensure_ascii=False) + "\n")
    _write_text(contract_py_path, _render_contract_py(view, sha))
    _write_text(contract_sha_path, sha + "\n")

    # User-owned policies (create once)
    reward_path = os.path.join(policies_dir, USER_REWARD_POLICY)
    dev_path = os.path.join(policies_dir, USER_DEVIATION_POLICY)

    created_reward = False
    created_dev = False

    if not _exists(reward_path):
        _write_text(reward_path, _render_default_reward_policy())
        created_reward = True

    if not _exists(dev_path):
        _write_text(dev_path, _render_default_deviation_policy())
        created_dev = True

    return ScaffoldResult(
        policies_dir=policies_dir,
        wrote_contract=True,
        created_reward_policy=created_reward,
        created_deviation_policy=created_dev,
        sha256=sha,
    )
