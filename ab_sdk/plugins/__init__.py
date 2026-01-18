"""
Plugin interfaces and convenience re-exports.

Plugins are small, swappable building blocks used by the SDK to:
- decode brain output spikes into actuator deltas (decoder)
- compute feedback/deviation signals (deviation)
- compute reward signals (reward)

Most users will import the ready-to-use helpers re-exported here.

Decoder (robot-agnostic)
------------------------

The server streams output activity as rows like:

    {"t": 190, "id": "V2", "bits": [0, 1, 0, ...]}

You provide a mapping describing how each output population ("id")
controls an actuator channel (any string you choose), and a scheme
for translating spikes into a control scalar.

Typical usage:

    from ab_sdk.plugins import MappingEntry, decode_stream_rows

    mapping = [
        MappingEntry(node_id="V2", channel="joint:3", scheme="bipolarSplit",
                     per_step_max=0.003, gain=0.5),
    ]

    commands = decode_stream_rows(rows, mapping)
    # -> [{"t": 190, "deltas": {"joint:3": ...}}, ...]

If your robot uses a "dq/dg" convention, you can optionally use:

    from ab_sdk.plugins import deltas_to_dq_dg

Deviation / Reward
------------------

Deviation and reward remain as optional policy plugins; you can use the
defaults or provide your own by subclassing BaseDeviation / BaseReward.
"""

# Decoder: robot-agnostic, row-stream -> deltas
from .decoder import (  # noqa: F401
    MappingEntry,
    decode_stream_rows,
    deltas_to_dq_dg,
    normalize_mapping,
)

# Deviation / Reward policies
from .deviation import BaseDeviation, DefaultDeviation  # noqa: F401
from .reward import BaseReward, DefaultReward  # noqa: F401

__all__ = [
    # decoder
    "MappingEntry",
    "decode_stream_rows",
    "deltas_to_dq_dg",
    "normalize_mapping",
    # deviation
    "BaseDeviation",
    "DefaultDeviation",
    # reward
    "BaseReward",
    "DefaultReward",
]
