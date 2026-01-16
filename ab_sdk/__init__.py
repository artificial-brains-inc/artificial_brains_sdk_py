"""Top-level package for ArtificialBrains Python SDK.

This package provides a client and helper classes to interact with the
Artificial Brains server over HTTP and WebSocket.  The SDK wraps the
low‑level REST and realtime protocols so that developers can focus on
providing sensor data, implementing control logic and defining reward/
feedback policies.  For a high level overview refer to the README in
the repository root.

The most important classes exported at the package level are:

```
from ab_sdk.client import ABClient
from ab_sdk.run_session import RunSession
from ab_sdk.input_streamer import InputStreamer
from ab_sdk.robot_loop import RobotLoop

from ab_sdk.plugins.decoder import DefaultDecoder, BipolarSplitDecoder
from ab_sdk.plugins.deviation import DefaultDeviation
from ab_sdk.plugins.reward import DefaultReward

from ab_sdk.utils.feedback import build_feedback_raster
from ab_sdk.utils.astro import astrocyte_modulation
```

These imports are re-exported here for convenience; you can import
directly from the underlying modules if you prefer more fine grained
control.  Each module includes extensive docstrings explaining its
purpose and how to use it.
"""

from .client import ABClient  # noqa: F401
from .run_session import RunSession  # noqa: F401
from .input_streamer import InputStreamer  # noqa: F401
from .robot_loop import RobotLoop  # noqa: F401

# plugins
from .plugins.decoder import DefaultDecoder, BipolarSplitDecoder  # noqa: F401
from .plugins.deviation import DefaultDeviation  # noqa: F401
from .plugins.reward import DefaultReward  # noqa: F401

# utils
from .utils.feedback import build_feedback_raster  # noqa: F401
from .utils.astro import astrocyte_modulation  # noqa: F401

__all__ = [
    "ABClient",
    "RunSession",
    "InputStreamer",
    "RobotLoop",
    "DefaultDecoder",
    "BipolarSplitDecoder",
    "DefaultDeviation",
    "DefaultReward",
    "build_feedback_raster",
    "astrocyte_modulation",
]