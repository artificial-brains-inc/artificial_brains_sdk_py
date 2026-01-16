"""Astrocyte modulation utilities.

This module implements a Python port of the astrocyte modulation
algorithm originally provided in JavaScript.  The goal of this
function is to update the synaptic weights of each layer based on
eligibility traces, a global reward signal and per‑layer dopamine
gains.  The function returns a new list of weights and updated
baselines to feed back into the next call.

You are free to replace or simplify this implementation to suit
your own learning rules.  The provided function follows the same
structure as the original but has been simplified for clarity and
readability.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Mapping, Tuple

logger = logging.getLogger(__name__)


def astrocyte_modulation(
    current_weights: Iterable[Dict[str, Any]],
    eligibility: Iterable[Dict[str, Any]],
    global_error: float = 0.5,
    astro_by_layer: Mapping[str, Dict[str, Any]] | None = None,
    default_eta: float = 0.1,
    prev_err: Any = 0.5,
    baseline_beta: float = 0.05,
    base_scale: float = 1.0,
    panic_scale: float = 100.0,
    min_clamp: float = 0.05,
    max_clamp: float = 5.0,
    min_weight: float = -10.0,
    max_weight: float = 10.0,
    panic_exponent: float = 4.0,
    mix_exponent: float = 2.5,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """Modulate weights based on eligibility and reward/error signals.

    Parameters
    ----------
    current_weights: iterable of dict
        A list of weight layers, each a dictionary with keys
        ``layerName`` and ``data`` (list of floats).
    eligibility: iterable of dict
        A list of eligibility layers; each dict must have ``layerName``
        and ``data`` (list of floats) matching the corresponding
        weight layer.
    global_error: float, optional
        Scalar error signal in ``[0,1]``; ``0`` means perfect,
        ``1`` means total failure.  The default is neutral ``0.5``.
    astro_by_layer: mapping, optional
        Optional mapping from layer names to per‑layer astrocyte
        configuration.  Each entry may contain ``dopamineGain`` and
        ``baseline`` values.
    default_eta: float, optional
        Base learning rate.
    prev_err: Any, optional
        A scalar or mapping containing previous error baselines for
        each layer.  This is updated and returned as the second
        element of the tuple.
    baseline_beta: float, optional
        Exponential decay factor controlling baseline adaptation.
    base_scale: float, optional
        Scaling factor applied when the agent is performing well.
    panic_scale: float, optional
        Scaling factor applied when the agent is performing poorly.
    min_clamp: float, optional
        Minimum absolute change allowed when stable.
    max_clamp: float, optional
        Maximum absolute change allowed when panicking.
    min_weight: float, optional
        Lower bound on weight values.
    max_weight: float, optional
        Upper bound on weight values.
    panic_exponent: float, optional
        Controls how aggressively the panic multiplier grows with error.
    mix_exponent: float, optional
        Controls how sharply to mix local and global error signals.

    Returns
    -------
    Tuple[List[Dict[str, Any]], Dict[str, float]]
        A tuple ``(updated_weights, next_baselines)`` where
        ``updated_weights`` is a list of the same shape as
        ``current_weights`` but with new ``data`` arrays and
        ``next_baselines`` is a mapping from layer names to baseline
        values for the next call.
    """
    astro_by_layer = astro_by_layer or {}
    # make a dict for easy lookup of eligibility by layer name
    elig_by_layer: Dict[str, List[float]] = {}
    for layer in eligibility:
        name = layer.get("layerName")
        if name and isinstance(layer.get("data"), list):
            elig_by_layer[name] = layer["data"]
    # prev_err may be scalar or mapping
    next_baselines: Dict[str, float] = {}
    updated_layers: List[Dict[str, Any]] = []
    for w_layer in current_weights:
        layer_name = w_layer.get("layerName")
        data = w_layer.get("data")
        if not layer_name or not isinstance(data, list):
            updated_layers.append(w_layer)
            continue
        elig = elig_by_layer.get(layer_name)
        if elig is None:
            # no eligibility, skip update
            updated_layers.append(w_layer)
            continue
        # get per‑layer config
        cfg = astro_by_layer.get(layer_name, {})
        # global score: invert global error (0 good -> 1 bad) to get success
        global_score = 1.0 - max(0.0, min(1.0, float(global_error)))
        # local dopamine gain is in [0,1] if provided
        local_score = cfg.get("dopamineGain")
        # compute mixing factor
        if local_score is not None:
            mix = (local_score ** mix_exponent)
            final_score = (local_score * (1 - mix)) + (global_score * mix)
        else:
            final_score = global_score
        # clamp final score to [0,1]
        final_score = max(0.0, min(1.0, float(final_score)))
        # determine baseline for this layer
        if isinstance(cfg.get("baseline"), (int, float)):
            baseline = float(cfg["baseline"])
        elif isinstance(prev_err, dict) and layer_name in prev_err:
            baseline = float(prev_err[layer_name])
        elif isinstance(prev_err, (int, float)):
            baseline = float(prev_err)
        else:
            baseline = 0.5
        # compute failure (1 - score)
        failure = 1.0 - final_score
        # dynamic multiplier: panic when failure is high
        dynamic_mult = base_scale + ((failure ** panic_exponent) * (panic_scale - base_scale))
        # dynamic clamp range between min_clamp and max_clamp
        current_cap = min_clamp + (failure * (max_clamp - min_clamp))
        # compute reinforcement prediction error (RPE)
        signal = (final_score - baseline)
        centered = signal * dynamic_mult
        # update baseline via exponential moving average
        new_base = baseline + baseline_beta * (final_score - baseline)
        next_baselines[layer_name] = new_base
        # apply weight updates
        W = list(data)
        E = list(elig)
        n = min(len(W), len(E))
        from random import random as _rand
        noise_scale = 0.001 * dynamic_mult
        for i in range(n):
            noise = (_rand() * 2 - 1) * noise_scale
            raw_delta = centered + noise
            # clamp update magnitude
            clean_delta = max(-current_cap, min(current_cap, raw_delta))
            dw = default_eta * clean_delta * E[i]
            val = W[i] + dw
            # hard clip weights
            if val > max_weight:
                val = max_weight
            if val < min_weight:
                val = min_weight
            W[i] = val
        updated_layers.append({"layerName": layer_name, "data": W})
        logger.debug(
            "Astrocyte update: layer=%s score=%.3f base=%.3f mult=%.3f cap=%.3f", layer_name, final_score, baseline, dynamic_mult, current_cap
        )
    return updated_layers, next_baselines