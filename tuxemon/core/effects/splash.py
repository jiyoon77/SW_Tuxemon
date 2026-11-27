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
    from tuxemon.monster.monster import Monster
    from tuxemon.session import Session
    from tuxemon.technique.technique import Technique


@dataclass
class SplashEffect(CoreEffect):
    """
    Applies the "splash" effect to a technique.

    This effect distributes damage across multiple targets. If the technique
    misses, the damage is reduced by dividing it with the specified divisor.
    Otherwise, full damage is applied to all valid targets.

    **Parameters**

    - ``divisor``: Integer value used to reduce damage when the technique
      misses. Damage is divided by this value.

    **Example**

    .. code-block:: json

        "effects": [
            "splash 2"
        ]
    """

    name = "splash"
    divisor: int

    def apply_tech_target(
        self, session: Session, tech: Technique, user: Monster, target: Monster
    ) -> TechEffectResult:
        combat = session.client.combat_session
        hit = combat.get_tech_hit(user)
        tech.hit = tech.accuracy >= hit

        base, mult = formula.simple_damage_calculate(tech, user, target)
        env_mult = get_environment_multiplier(session, user)
        damage = apply_environment_bonus(base, env_mult)
        targets = combat.get_targets(tech, user, target)

        partial_hit = False
        if not tech.hit:
            damage //= self.divisor
            partial_hit = True

        enemy_side = combat.get_own_monsters(target)
        if sum(1 for m in targets if m in enemy_side) > 1:
            damage = int(damage * 0.75)

        # keep at least 1 after every reduction unless it was 0 already
        if base > 0:
            damage = max(1, damage)

        if targets:
            for monster in targets:
                hp_before = monster.current_hp
                monster.current_hp = max(0, hp_before - damage)
                combat.record_hp_change(
                    monster, hp_before, actor=user, technique=tech
                )
                # to avoid double registration in the self._damage_map
                if monster != target:
                    combat.enqueue_damage(user, monster, damage)

        extras = ["combat_splash_partial"] if partial_hit and damage else []
        message = environment_message(env_mult)
        if damage and message:
            extras.append(message)
        return TechEffectResult(
            name=tech.name,
            success=bool(damage),
            damage=damage,
            should_tackle=bool(damage),
            element_multiplier=mult,
            extras=extras,
        )
