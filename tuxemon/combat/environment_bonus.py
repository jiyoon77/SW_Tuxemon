# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
"""Damage bonus for monsters whose element suits the weather and season."""

from __future__ import annotations

import logging
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter

from tuxemon.constants import paths
from tuxemon.database.yaml_utils import load_yaml
from tuxemon.db import Modifier
from tuxemon.modifiers import ModifierMode, ModifiersHandler

if TYPE_CHECKING:
    from tuxemon.monster.monster import Monster
    from tuxemon.session import Session

logger = logging.getLogger(__name__)

SEASON_MODIFIERS_FILE: Final[Path] = (
    paths.mods_folder / "tuxemon" / "db" / "season_modifiers.yaml"
)
MIN_ENVIRONMENT_MULTIPLIER: Final[float] = 0.5
MAX_ENVIRONMENT_MULTIPLIER: Final[float] = 1.5

BOOST_MESSAGE: Final[str] = "combat_environment_boost"
WEAKEN_MESSAGE: Final[str] = "combat_environment_weaken"

_season_adapter = TypeAdapter(dict[str, list[Modifier]])


def load_season_modifiers(
    path: Path = SEASON_MODIFIERS_FILE,
) -> dict[str, list[Modifier]]:
    """
    Reads the per-season modifiers. Returns an empty mapping (no season
    bonus) and logs a warning when the file is missing or invalid.
    """
    if not path.exists():
        logger.warning(f"Season modifiers file '{path}' not found.")
        return {}
    try:
        data = load_yaml(path) or {}
        return _season_adapter.validate_python(data)
    except Exception as exc:
        logger.warning(f"Invalid season modifiers file '{path}': {exc}")
        return {}


@cache
def _default_season_modifiers() -> dict[str, list[Modifier]]:
    return load_season_modifiers()


def _multiplier(modifiers: list[Modifier], monster: Monster) -> float:
    if not modifiers:
        return 1.0
    handler = ModifiersHandler(list(modifiers))
    return handler.get_multiplier(monster, ModifierMode.CUMULATIVE)


def get_weather_multiplier(session: Session, monster: Monster) -> float:
    manager = getattr(session.client, "weather_manager", None)
    weather = manager.current_weather if manager is not None else None
    if weather is None:
        return 1.0
    return _multiplier(weather.modifiers, monster)


def get_season_multiplier(
    session: Session,
    monster: Monster,
    season_modifiers: dict[str, list[Modifier]] | None = None,
) -> float:
    try:
        season = session.time.get_time_variables().season
    except Exception as exc:
        logger.warning(f"Could not determine the season: {exc}")
        return 1.0
    table = (
        season_modifiers
        if season_modifiers is not None
        else _default_season_modifiers()
    )
    return _multiplier(table.get(season, []), monster)


def get_environment_multiplier(
    session: Session,
    monster: Monster,
    season_modifiers: dict[str, list[Modifier]] | None = None,
) -> float:
    """
    Combined weather and season multiplier for damage dealt by ``monster``,
    based on its current element types and clamped to 0.5 - 1.5.
    """
    mult = get_weather_multiplier(session, monster) * get_season_multiplier(
        session, monster, season_modifiers
    )
    return max(
        MIN_ENVIRONMENT_MULTIPLIER, min(MAX_ENVIRONMENT_MULTIPLIER, mult)
    )


def apply_environment_bonus(damage: int, multiplier: float) -> int:
    """Scales damage, keeping at least 1 if there was any damage."""
    if damage <= 0:
        return damage
    return max(1, int(damage * multiplier))


def environment_message(multiplier: float) -> str | None:
    if multiplier > 1.0:
        return BOOST_MESSAGE
    if multiplier < 1.0:
        return WEAKEN_MESSAGE
    return None
