# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class BattleLogEntry:
    turn: int
    action_id: int
    sequence: int
    event_type: Literal["technique_result", "damage"]
    actor_id: UUID
    actor_name: str
    target_id: UUID
    target_name: str
    technique_slug: str
    technique_name: str
    outcome: Literal["success", "failure"]
    hp_change: int | None = None
