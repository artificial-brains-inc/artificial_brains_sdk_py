"""Decoder plugin classes for converting output spikes into robot commands.

The decoder is responsible for taking the raw spike activity from the
brain (a dictionary mapping output IDs to matrices of shape
``gamma × outputN``) and producing a movement command.  This
command is a dictionary containing at minimum the keys ``dq`` (a
list of joint deltas) and ``dg`` (gripper delta).  You are free to
include additional keys to support custom actuators.

To implement your own decoder plugin, subclass
:class:`BaseDecoder` and override :meth:`decode`.  See
:class:`BipolarSplitDecoder` for a concrete implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


class BaseDecoder:
    """Abstract base class for decoders.

    Concrete subclasses must override :meth:`decode`.
    """

    def decode(self, outputs: Dict[str, List[List[int]]], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert output spike matrices into a command dictionary.

        Parameters
        ----------
        outputs: dict
            Mapping from output IDs (strings) to matrices of
            ``gamma × outputN`` ints.  Each element is either 0 or 1
            indicating a spike in that timestep at that neuron.
        context: dict
            Additional context including the raw telemetry and session.

        Returns
        -------
        dict or None
            A command dictionary containing at least ``dq`` and ``dg``.
            If `None` is returned then no command is emitted.
        """
        raise NotImplementedError


class DefaultDecoder(BaseDecoder):
    """A decoder that generates zero movement.

    This decoder simply returns a command dict with zero deltas and
    zero gripper movement.  It is useful as a placeholder when you
    want to record or debug output activity without moving the robot.
    """

    def decode(self, outputs: Dict[str, List[List[int]]], context: Dict[str, Any]) -> Dict[str, Any]:
        session = context.get("session")
        dof = 0
        # try to infer degrees of freedom from session state; fallback to 0
        if session is not None:
            # count unique joints across mappings if mapping is present
            dof = len(session.io_outputs)  # approximate; user should override
        return {"dq": [0.0] * dof, "dg": 0.0}


@dataclass
class MappingEntry:
    """A single mapping from an output population to a joint channel.

    Attributes
    ----------
    output_id: str
        Identifier of the output node in the brain.
    joint_index: int
        Index of the joint that this output controls.
    gain: float
        Scalar gain applied to the decoded value.
    per_step_max: float
        Maximum magnitude of the step per cycle.  The decoded value is
        multiplied by this to produce a joint delta.
    deadzone: float
        Values whose absolute magnitude is below this threshold are
        treated as zero.
    """

    output_id: str
    joint_index: int
    gain: float = 1.0
    per_step_max: float = 0.01
    deadzone: float = 0.0


class BipolarSplitDecoder(BaseDecoder):
    """Decode output spikes using a bipolar split scheme.

    Each output population is split into two halves.  Spikes in the
    first half are interpreted as positive contributions; spikes in
    the second half as negative.  The difference between the counts
    of positive and negative spikes is normalized by the half size to
    produce a value in ``[-1,1]``.  This value is then scaled by the
    mapping entry's gain and per‑step maximum to yield the joint
    movement.  Values within the deadzone are clipped to zero.

    The decoder is configured with a list of :class:`MappingEntry`
    objects.  Each entry associates an output ID with a joint index
    and decoding parameters.  When decode is called, for each entry
    the corresponding output matrix is looked up in the provided
    outputs dictionary.  If an entry refers to a non‑existent output
    ID then it is ignored.
    """

    def __init__(self, mapping: Iterable[MappingEntry]):
        self.mapping = list(mapping)

    def decode(self, outputs: Dict[str, List[List[int]]], context: Dict[str, Any]) -> Dict[str, Any]:
        # determine degrees of freedom (max joint index + 1)
        dof = 0
        for entry in self.mapping:
            dof = max(dof, entry.joint_index + 1)
        dq = [0.0] * dof
        dg = 0.0
        for entry in self.mapping:
            matrix = outputs.get(entry.output_id)
            if not matrix:
                continue
            # compute pos/neg counts across all timesteps
            N = len(matrix[0]) if matrix else 0
            if N == 0:
                continue
            half = N // 2
            pos_count = 0
            neg_count = 0
            for row in matrix:
                # ensure row length
                # count spikes in first half and second half
                for i, bit in enumerate(row[:half]):
                    pos_count += 1 if bit else 0
                for bit in row[half:]:
                    neg_count += 1 if bit else 0
            total = pos_count + neg_count
            if total == 0:
                value = 0.0
            else:
                value = (pos_count - neg_count) / float(max(1, half * len(matrix)))
            # apply deadzone
            if abs(value) < entry.deadzone:
                value = 0.0
            # apply gain and scale
            delta = entry.gain * value * entry.per_step_max
            # accumulate into joint
            if entry.joint_index == -1:
                # treat -1 as gripper channel
                dg += delta
            else:
                dq[entry.joint_index] += delta
        return {"dq": dq, "dg": dg}