"""Plugin base classes and reexports.

This module defines the interfaces expected by the SDK for decoder,
deviation and reward plugins.  By subclassing the appropriate base
class you can provide custom implementations that will be called at
runtime by the :class:`~ab_sdk.run_session.RunSession` or
:class:`~ab_sdk.robot_loop.RobotLoop`.

You can also import the default implementations exported here:

```
from ab_sdk.plugins import DefaultDecoder, BipolarSplitDecoder
from ab_sdk.plugins import DefaultDeviation
from ab_sdk.plugins import DefaultReward
```
"""

from .decoder import BaseDecoder, DefaultDecoder, BipolarSplitDecoder  # noqa: F401
from .deviation import BaseDeviation, DefaultDeviation  # noqa: F401
from .reward import BaseReward, DefaultReward  # noqa: F401

__all__ = [
    "BaseDecoder", "DefaultDecoder", "BipolarSplitDecoder",
    "BaseDeviation", "DefaultDeviation",
    "BaseReward", "DefaultReward",
]