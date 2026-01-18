"""
Top-level package for ArtificialBrains Python SDK.

This package provides a client and helper classes to interact with the
ArtificialBrains server over HTTP and realtime (Socket.IO/WebSocket-style)
events. The SDK wraps the low-level REST + realtime protocols so developers
can focus on:
- providing sensor inputs (camera, depth, etc.)
- turning brain outputs (spikes) into actuator commands
- defining reward / feedback (optional)

High-level imports (recommended):

    from ab_sdk import ABClient, RunSession, InputStreamer, RobotLoop

Decoding output spikes (robot-agnostic):

    from ab_sdk.plugins.decoder import MappingEntry, decode_stream_rows

Optional convenience helper (if your robot uses dq/dg style):

    from ab_sdk.plugins.decoder import deltas_to_dq_dg

Reward / deviation plugins (optional defaults):

    from ab_sdk.plugins.deviation import DefaultDeviation
    from ab_sdk.plugins.reward import DefaultReward
"""

from .client import ABClient  # noqa: F401
from .run_session import RunSession  # noqa: F401
from .input_streamer import InputStreamer  # noqa: F401
from .robot_loop import RobotLoop  # noqa: F401

# plugins (robot-agnostic decoding)
from .plugins.decoder import (  # noqa: F401
    MappingEntry,
    decode_stream_rows,
    deltas_to_dq_dg,
)

# optional defaults (policies)
from .plugins.deviation import DefaultDeviation  # noqa: F401
from .plugins.reward import DefaultReward  # noqa: F401

__all__ = [
    "ABClient",
    "RunSession",
    "InputStreamer",
    "RobotLoop",
    # decoder plugin
    "MappingEntry",
    "decode_stream_rows",
    "deltas_to_dq_dg",
    # policies
    "DefaultDeviation",
    "DefaultReward",
]
