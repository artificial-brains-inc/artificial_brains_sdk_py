# ab_sdk/maps/reward_map.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable


@dataclass(frozen=True)
class LocalRewardBinding:
    layer: str
    from_output: str
    meta: Dict[str, Any] | None = None


class RewardMap:
    """Only local rewards are indexed here.

    Global rewards are skipped here because they are sent directly.
    A reward entry is considered local when `fromOutput` exists and is not
    the literal string "Global".

    The `layer` is the exact STDP3 layer where the reward must be applied.
    """

    def __init__(self, entries: Iterable[Dict[str, Any]]) -> None:
        self.by_layer: Dict[str, LocalRewardBinding] = {}
        self.by_from_output: Dict[str, list[LocalRewardBinding]] = {}

        for raw in entries or []:
            from_output = str(raw.get("fromOutput") or "").strip()

            if not from_output:
                continue
            if from_output == "Global":
                continue

            layer = str(raw.get("layer") or "").strip()

            if not layer:
                raise ValueError("reward map entry missing layer")

            if layer in self.by_layer:
                raise ValueError(f"duplicate local reward layer: {layer}")

            binding = LocalRewardBinding(
                layer=layer,
                from_output=from_output,
                meta=dict(raw),
            )

            self.by_layer[layer] = binding
            self.by_from_output.setdefault(from_output, []).append(binding)

    @classmethod
    def from_contract(cls, contract: Dict[str, Any]) -> "RewardMap":
        maps = contract.get("maps") or {}
        return cls(maps.get("reward_map") or [])

    def get(self, layer: str) -> LocalRewardBinding:
        try:
            return self.by_layer[layer]
        except KeyError as exc:
            raise KeyError(f"unknown local reward layer '{layer}'") from exc

    def get_by_output(self, from_output: str) -> list[LocalRewardBinding]:
        return self.by_from_output.get(str(from_output).strip(), [])