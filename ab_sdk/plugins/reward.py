"""Reward plugin classes for computing global and per‑layer reward signals.

The reward plugin computes a scalar representing overall goodness of
the current behaviour and optionally individual rewards for each
STDP3 layer.  Values should be in the range ``[0,1]``.  Higher
values indicate better performance (positive reward), while lower
values are interpreted as errors or worse performance.

To implement a custom reward plugin subclass
:class:`BaseReward` and override :meth:`compute`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


class BaseReward:
    """Abstract base class for reward policies."""

    def compute(self, telemetry: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        """Compute the global and per‑layer reward.

        Parameters
        ----------
        telemetry: dict
            The full telemetry payload received in a cycle update.

        Returns
        -------
        Tuple[float, Dict[str, float]]
            A tuple ``(global_reward, by_layer)`` where ``global_reward``
            is a scalar in ``[0,1]`` and ``by_layer`` maps layer names to
            scalars in ``[0,1]``.
        """
        raise NotImplementedError


class DefaultReward(BaseReward):
    """Reward policy that assigns a neutral reward.

    This policy always returns ``0.5`` for the global reward and an
    empty dictionary for layer rewards.  It is useful when you want
    synaptic changes to be governed solely by the brain's internal
    dynamics without any external reinforcement.
    """

    def __init__(self, session: Any) -> None:
        self.session = session

    def compute(self, telemetry: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        return 0.5, {}