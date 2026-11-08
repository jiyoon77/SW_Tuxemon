# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from datetime import datetime
from unittest.mock import patch

import pytest
from pygame.surface import Surface

from tuxemon.time_handler import TimeHandler
from tuxemon.world.time_tint import (
    DEFAULT_TIME_TINT,
    MAX_TINT_ALPHA,
    TIME_TINT_FILE,
    ColorFade,
    TimeTintRenderer,
    load_time_tint,
)


@pytest.fixture
def clock(monkeypatch):
    """Pins TimeHandler to a settable hour."""
    state = {"hour": 10}

    def fake_now(self):
        return datetime(2026, 6, 1, state["hour"], 30)

    monkeypatch.setattr(TimeHandler, "get_current_time", fake_now)
    return state


@pytest.mark.parametrize(
    "hour,stage",
    [
        pytest.param(5, "dawn", id="dawn"),
        pytest.param(9, "morning", id="morning"),
        pytest.param(13, "afternoon", id="afternoon"),
        pytest.param(17, "dusk", id="dusk"),
        pytest.param(22, "night", id="night"),
        pytest.param(2, "night", id="night_after_midnight"),
    ],
)
def test_color_per_stage(clock, hour, stage):
    clock["hour"] = hour
    tint = TimeTintRenderer(TimeHandler("northern"), dict(DEFAULT_TIME_TINT))
    assert tint.stage == stage
    assert tint.current_color == DEFAULT_TIME_TINT[stage]


def test_shipped_file_matches_defaults():
    assert load_time_tint(TIME_TINT_FILE) == DEFAULT_TIME_TINT


def test_missing_file_uses_defaults(tmp_path):
    with patch("tuxemon.world.time_tint.logger") as log:
        colors = load_time_tint(tmp_path / "missing.yaml")
    assert colors == DEFAULT_TIME_TINT
    assert "not found" in log.warning.call_args.args[0]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("night: [1, 2, 3]\n", id="too_few_channels"),
        pytest.param("night: [1, 2, 3, 999]\n", id="out_of_range"),
        pytest.param("night: red\n", id="not_a_list"),
        pytest.param("- 1\n- 2\n", id="top_level_list"),
        pytest.param("night: [1, 2\n", id="broken_yaml"),
    ],
)
def test_broken_file_uses_defaults(tmp_path, content):
    path = tmp_path / "time_tint.yaml"
    path.write_text(content, encoding="utf-8")
    with patch("tuxemon.world.time_tint.logger") as log:
        assert load_time_tint(path) == DEFAULT_TIME_TINT
    assert "Invalid time tint file" in log.warning.call_args.args[0]


def test_alpha_is_clamped(tmp_path):
    path = tmp_path / "time_tint.yaml"
    path.write_text("night: [0, 0, 0, 255]\n", encoding="utf-8")
    colors = load_time_tint(path)
    assert colors["night"] == (0, 0, 0, MAX_TINT_ALPHA)
    assert colors["dusk"] == DEFAULT_TIME_TINT["dusk"]


def test_fade_values():
    fade = ColorFade((0, 0, 0, 0), duration=3.0)
    fade.fade_to((20, 30, 80, 120))
    assert fade.current == (0, 0, 0, 0)
    fade.update(1.5)
    assert fade.current == (10, 15, 40, 60)
    fade.update(1.5)
    assert fade.current == (20, 30, 80, 120)
    fade.update(5.0)
    assert fade.current == (20, 30, 80, 120)


def test_fade_from_middle_of_previous_fade():
    fade = ColorFade((0, 0, 0, 0), duration=3.0)
    fade.fade_to((200, 90, 60, 60))
    fade.update(1.5)
    fade.fade_to((0, 0, 0, 0))
    assert fade.current == (100, 45, 30, 30)
    fade.update(3.0)
    assert fade.current == (0, 0, 0, 0)


def test_stage_change_fades_after_check(clock):
    clock["hour"] = 19
    tint = TimeTintRenderer(TimeHandler("northern"), dict(DEFAULT_TIME_TINT))
    assert tint.stage == "dusk"

    clock["hour"] = 20
    tint.update(0.5)
    # stage is only polled once per second
    assert tint.stage == "dusk"
    tint.update(0.5)
    assert tint.stage == "night"
    assert tint.current_color == DEFAULT_TIME_TINT["dusk"]

    tint.update(1.5)
    assert tint.current_color == (110, 60, 70, 90)
    tint.update(1.5)
    assert tint.current_color == DEFAULT_TIME_TINT["night"]


def test_snap_skips_fade(clock):
    clock["hour"] = 13
    tint = TimeTintRenderer(TimeHandler("northern"), dict(DEFAULT_TIME_TINT))
    clock["hour"] = 22
    tint.snap()
    assert tint.stage == "night"
    assert tint.current_color == DEFAULT_TIME_TINT["night"]


def test_draw_blends_tint(clock):
    clock["hour"] = 22
    tint = TimeTintRenderer(TimeHandler("northern"), dict(DEFAULT_TIME_TINT))
    surface = Surface((16, 16))
    surface.fill((255, 255, 255))
    tint.draw(surface)
    r, g, b, _ = surface.get_at((0, 0))
    assert r < 255 and g < 255 and b < 255

    clock["hour"] = 10
    tint.snap()
    surface.fill((255, 255, 255))
    tint.draw(surface)
    assert tuple(surface.get_at((0, 0)))[:3] == (255, 255, 255)
