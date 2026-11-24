# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tuxemon import formula
from tuxemon.combat.environment_bonus import (
    apply_environment_bonus,
    environment_message,
    get_environment_multiplier,
)
from tuxemon.core.core_effect import CoreEffect, TechEffectResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tuxemon.monster.monster import Monster
    from tuxemon.session import Session
    from tuxemon.technique.technique import Technique

# damage each enemy takes when more than one of them is hit at once
MULTI_TARGET_MODIFIER = 0.75


@dataclass
class DamageEffect(CoreEffect):
    """
    Applies damage to one or more target monsters.

    This effect is triggered when ``damage`` is defined in a technique's
    effect list. It calculates damage based on the technique, user, and
    target, then reduces the target's HP accordingly. The damage is scaled
    by the weather/season bonus of the user's element types.

    **Example**

    .. code-block:: json

        "effects": [
            "damage"
        ]
    """

    name = "damage"

    def apply_tech_target(
        self, session: Session, tech: Technique, user: Monster, target: Monster
    ) -> TechEffectResult:
        damage = 0
        mult = 1.0
        targets: list[Monster] = []
        enemy_side: Sequence[Monster] = []

        combat = session.client.combat_session
        hit = combat.get_tech_hit(user)
        tech.hit = tech.accuracy >= hit

        if tech.hit:
            targets = combat.get_targets(tech, user, target)
            enemy_side = combat.get_own_monsters(target)

        spread = sum(1 for m in targets if m in enemy_side) > 1
        env_mult = (
            get_environment_multiplier(session, user) if targets else 1.0
        )

        for monster in targets:
            base, m = formula.simple_damage_calculate(tech, user, monster)
            dmg = apply_environment_bonus(base, env_mult)
            if spread and monster in enemy_side:
                dmg = int(dmg * MULTI_TARGET_MODIFIER)
            # keep at least 1 after every reduction unless it was 0 already
            if base > 0:
                dmg = max(1, dmg)
            hp_before = monster.current_hp
            monster.current_hp = max(0, hp_before - dmg)
            hp_change = monster.current_hp - hp_before
            if hp_change < 0:
                combat.record_battle_event(
                    "damage", user, monster, tech, "success", hp_change
                )
            if monster == target:
                damage, mult = dmg, m
            else:
                # to avoid double registration in the self._damage_map
                combat.enqueue_damage(user, monster, dmg)

        extras: list[str] = []
        message = environment_message(env_mult)
        if damage and message:
            extras.append(message)

        return TechEffectResult(
            name=tech.name,
            damage=damage,
            element_multiplier=mult,
            should_tackle=bool(damage),
            success=bool(damage),
            extras=extras,
        )
