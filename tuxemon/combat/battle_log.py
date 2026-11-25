# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

StatusEventType = Literal[
    "status_applied", "status_stacked", "status_removed", "status_blocked"
]
BattleEventType = (
    StatusEventType
    | Literal[
        "technique_result",
        "damage",
        "healing",
        "status_damage",
        "item_result",
        "capture_result",
        "swap",
        "replacement",
        "faint",
    ]
)


@dataclass(frozen=True)
class BattleLogEntry:
    turn: int
    action_id: int
    sequence: int
    event_type: BattleEventType
    actor_id: UUID | None
    actor_name: str | None
    target_id: UUID | None
    target_name: str | None
    technique_slug: str | None
    technique_name: str | None
    outcome: Literal["success", "failure"]
    hp_change: int | None = None
    hit_count: int | None = None
    item_slug: str | None = None
    item_name: str | None = None
    status_slug: str | None = None
    status_name: str | None = None
    blocked_by: str | None = None
    blocked_reason: str | None = None
    num_shakes: int | None = None
