"""Deviation plugin classes for computing feedback error signals.

A deviation plugin produces a per‑timestep deviation (error) signal
for each feedback input ID.  The brain uses this signal to build a
feedback raster which modulates the synaptic activity.  Values
should lie in ``[-1,1]``; positive deviations indicate that the
current behavior is above some target and negative values mean it is
below.  See the README for details.

To implement your own deviation plugin subclass
:class:`BaseDeviation` and override :meth:`compute`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class BaseDeviation:
    """Abstract base class for deviation policies."""

    def compute(self, telemetry: Dict[str, Any]) -> Dict[str, List[float]]:
        """Compute deviations for feedback inputs.

        Parameters
        ----------
        telemetry: dict
            The full telemetry payload received in a cycle update.

        Returns
        -------
        dict
            A mapping from feedback input IDs to lists of floats of
            length ``gamma``.  Values must be in the range ``[-1,1]``.
        """
        raise NotImplementedError


class DefaultDeviation(BaseDeviation):
    """Deviation policy that returns zero for all timesteps.

    This simply produces a list of zeros for each feedback input ID
    defined in the session contract.  It is a reasonable default when
    you do not want to apply any correction to the baseline activity.
    """

    def __init__(self, session: Any) -> None:
        # session is used to access gamma and feedback inputs
        self.session = session

    def compute(self, telemetry: Dict[str, Any]) -> Dict[str, List[float]]:
        gamma = self.session.gamma if hasattr(self.session, 'gamma') else 64
        deviations: Dict[str, List[float]] = {}
        for fb_id in self.session.io_feedback.keys():
            deviations[fb_id] = [0.0] * gamma
        return deviations