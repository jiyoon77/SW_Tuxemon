# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
"""Colour tint drawn over outdoor maps depending on the stage of day."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final

from pygame import SRCALPHA
from pygame.surface import Surface

from tuxemon.constants import paths
from tuxemon.database.yaml_utils import load_yaml

if TYPE_CHECKING:
    from tuxemon.time_handler import TimeHandler

logger = logging.getLogger(__name__)

RGBA = tuple[int, int, int, int]

TIME_TINT_FILE: Final[Path] = (
    paths.mods_folder / "tuxemon" / "db" / "time_tint.yaml"
)
MAX_TINT_ALPHA: Final[int] = 160
TINT_CHECK_INTERVAL: Final[float] = 1.0
TINT_FADE_SECONDS: Final[float] = 3.0

DEFAULT_TIME_TINT: Final[dict[str, RGBA]] = {
    "dawn": (255, 170, 120, 40),
    "morning": (0, 0, 0, 0),
    "afternoon": (0, 0, 0, 0),
    "dusk": (200, 90, 60, 60),
    "night": (20, 30, 80, 120),
}


def _parse_color(value: object) -> RGBA:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"expected [R, G, B, A], got {value!r}")
    channels = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise ValueError(f"colour channel {channel!r} is not an integer")
        if not 0 <= channel <= 255:
            raise ValueError(f"colour channel {channel} is out of 0-255")
        channels.append(channel)
    r, g, b, a = channels
    return r, g, b, min(a, MAX_TINT_ALPHA)


def load_time_tint(path: Path = TIME_TINT_FILE) -> dict[str, RGBA]:
    """
    Reads the stage-of-day colours. Falls back to the built-in defaults
    (with a warning) when the file is missing or malformed. Alpha values
    above MAX_TINT_ALPHA are clamped.
    """
    colors = dict(DEFAULT_TIME_TINT)
    if not path.exists():
        logger.warning(f"Time tint file '{path}' not found, using defaults.")
        return colors

    try:
        data = load_yaml(path)
        if not isinstance(data, dict):
            raise ValueError("top level must be a mapping")
        loaded = {
            str(stage): _parse_color(value) for stage, value in data.items()
        }
    except Exception as exc:
        logger.warning(
            f"Invalid time tint file '{path}': {exc}. Using defaults."
        )
        return colors

    colors.update(loaded)
    return colors


def lerp_color(start: RGBA, end: RGBA, t: float) -> RGBA:
    t = max(0.0, min(1.0, t))
    r, g, b, a = (round(s + (e - s) * t) for s, e in zip(start, end))
    return r, g, b, a


class ColorFade:
    """Linear RGBA transition between two colours over a fixed duration."""

    def __init__(self, color: RGBA, duration: float) -> None:
        self.duration = duration
        self._start = color
        self._target = color
        self._elapsed = duration

    @property
    def current(self) -> RGBA:
        if self.duration <= 0:
            return self._target
        return lerp_color(
            self._start, self._target, self._elapsed / self.duration
        )

    @property
    def target(self) -> RGBA:
        return self._target

    def snap(self, color: RGBA) -> None:
        self._start = color
        self._target = color
        self._elapsed = self.duration

    def fade_to(self, color: RGBA) -> None:
        self._start = self.current
        self._target = color
        self._elapsed = 0.0

    def update(self, dt: float) -> None:
        self._elapsed = min(self.duration, self._elapsed + dt)


class TimeTintRenderer:
    """
    Keeps track of the stage of day and draws the matching tint.

    The stage is only queried every ``check_interval`` seconds. A change of
    stage starts a ``fade_duration`` second transition; ``snap`` jumps to
    the current stage colour (used when entering a map).
    """

    def __init__(
        self,
        time_handler: TimeHandler,
        colors: dict[str, RGBA] | None = None,
        check_interval: float = TINT_CHECK_INTERVAL,
        fade_duration: float = TINT_FADE_SECONDS,
    ) -> None:
        self.time_handler = time_handler
        self.colors = colors if colors is not None else load_time_tint()
        self.check_interval = check_interval
        self._since_check = 0.0
        self.stage = self._current_stage()
        self.fade = ColorFade(self.color_for(self.stage), fade_duration)
        self._layer: Surface | None = None

    def _current_stage(self) -> str:
        return self.time_handler.get_time_variables().stage_of_day

    def color_for(self, stage: str) -> RGBA:
        return self.colors.get(stage, (0, 0, 0, 0))

    @property
    def current_color(self) -> RGBA:
        return self.fade.current

    def snap(self) -> None:
        self.stage = self._current_stage()
        self.fade.snap(self.color_for(self.stage))
        self._since_check = 0.0

    def update(self, dt: float) -> None:
        self.fade.update(dt)
        self._since_check += dt
        if self._since_check < self.check_interval:
            return
        self._since_check = 0.0
        stage = self._current_stage()
        if stage != self.stage:
            logger.debug(f"Stage of day changed: {self.stage} -> {stage}")
            self.stage = stage
            self.fade.fade_to(self.color_for(stage))

    def draw(self, surface: Surface) -> None:
        color = self.current_color
        if color[3] <= 0:
            return
        size = surface.get_size()
        if self._layer is None or self._layer.get_size() != size:
            self._layer = Surface(size, SRCALPHA)
        self._layer.fill(color)
        surface.blit(self._layer, (0, 0))
