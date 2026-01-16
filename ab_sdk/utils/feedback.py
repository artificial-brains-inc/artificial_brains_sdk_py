"""Utilities for building feedback correction rasters.

This module provides a helper function to convert a per‑timestep
deviation signal into a 2D raster suitable for a feedback input.  The
raster is a flat list of length ``gamma * N`` where ``gamma`` is
usually 64 and ``N`` is the size of the feedback population (128 by
default).  Each element of the raster should be a float in
``[-1,1]``.  Positive values encode excitatory spikes and negative
values encode inhibitory spikes.  Zero means no spike at that
position.

The algorithm implemented here is deliberately conservative and easy
to understand: for each timestep we write a spike into each neuron
with a probability proportional to the magnitude of the deviation.
Positive deviations produce +1 spikes, negative deviations produce -1
spikes.  If a baseline raster is provided then non‑zero entries in
the baseline are copied into the output before any deviations are
applied.  This allows preservation of pre‑existing activity.

This is not a faithful port of the original JavaScript
implementation, but it captures the core idea of producing a sparse
correction signal scaled by deviation magnitude.  Users with more
advanced requirements should implement their own raster generator.
"""

from __future__ import annotations

import logging
import random
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


def build_feedback_raster(
    deviations: Iterable[float],
    N: int = 128,
    baseline: Optional[Iterable[float]] = None,
    outcome: float = 0.0,
    dead_zone: float = 0.08,
    seed: Optional[int] = None,
) -> List[float]:
    """Generate a feedback raster from per‑timestep deviations.

    Parameters
    ----------
    deviations: iterable of float
        Sequence of length ``gamma`` containing values in ``[-1,1]``.
    N: int, optional
        Population size of the feedback raster (default 128).
    baseline: iterable of float, optional
        Optional baseline raster to copy into the output before
        deviations are applied.  Must have length ``gamma * N``.
    outcome: float, optional
        Optional reward or outcome pulse to inject near the end of
        the raster.  Ignored in this simplified implementation.
    dead_zone: float, optional
        Deviations with absolute value below this threshold produce
        no spikes.
    seed: int, optional
        Seed for the random number generator.  Use this to obtain
        reproducible rasters.

    Returns
    -------
    List[float]
        A flat list of length ``len(deviations) * N`` containing
        floats in ``[-1,1]`` representing signed spikes.
    """
    # Convert deviations to list for length
    dev_list = list(deviations)
    T = len(dev_list)
    if baseline is not None and len(baseline) != T * N:
        raise ValueError("baseline length does not match gamma * N")
    # prepare output raster
    raster: List[float] = [0.0] * (T * N)
    if baseline is not None:
        # copy baseline values
        raster[:] = list(baseline)
    rng = random.Random(seed)
    for t in range(T):
        dev = max(-1.0, min(1.0, float(dev_list[t])))
        magnitude = abs(dev)
        if magnitude <= dead_zone:
            continue
        # determine sign
        sign = 1.0 if dev >= 0 else -1.0
        # probability scales linearly from dead_zone to 1
        prob = (magnitude - dead_zone) / max(1e-9, (1.0 - dead_zone))
        for i in range(N):
            if rng.random() < prob:
                raster[t * N + i] = sign
    # TODO: outcome pulse injection could be added here if needed
    return raster