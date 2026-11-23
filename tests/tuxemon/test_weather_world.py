# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
"""Weather roll interval, rule loading, weather_is and save/load."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tuxemon.constants import paths
from tuxemon.event.actions.load_weather import LoadWeatherAction
from tuxemon.event.conditions.weather_is import WeatherIsCondition
from tuxemon.save_system.save_state import WorldSave
from tuxemon.states.world_state import WorldState
from tuxemon.world.weather import (
    Temperature,
    WeatherTransitionRule,
    WeatherTransitionRulesModel,
    Wind,
    WorldWeatherManager,
    load_default_weather_rules,
    load_weather_transition_rules,
)

WEATHER_SLUGS = [
    "sunny",
    "cloudy",
    "rain",
    "snow",
    "thunderstorm",
    "foggy",
    "misty",
    "windy",
    "hot",
    "freezing",
]


@pytest.fixture
def fake_db():
    fake = SimpleNamespace(database={"weather": dict.fromkeys(WEATHER_SLUGS)})
    with (
        patch("tuxemon.world.weather.db", fake),
        patch("tuxemon.event.conditions.weather_is.db", fake),
    ):
        yield fake


@pytest.fixture
def weather_patch():
    def dummy_weather(slug):
        obj = MagicMock()
        obj.slug = slug
        obj.current_temperature = Temperature("mild")
        obj.current_wind = Wind("calm")
        return obj

    with patch("tuxemon.world.weather.Weather.get", side_effect=dummy_weather):
        yield


def always_rain(interval=60.0):
    return WeatherTransitionRulesModel(
        transitions={
            "sunny": [
                WeatherTransitionRule(next_slug="rain", trigger_chance=1.0)
            ]
        },
        roll_interval_seconds=interval,
    )


# --- roll interval -----------------------------------------------------------


def test_roll_only_after_interval(weather_patch, fake_db):
    mgr = WorldWeatherManager(rules_model=always_rain(), seed=1)
    with patch.object(mgr, "advance_turn", wraps=mgr.advance_turn) as roll:
        for _ in range(59):
            mgr.update(1)
        assert roll.call_count == 0
        assert mgr.current_slug == "sunny"
        mgr.update(1)
        assert roll.call_count == 1
    assert mgr.current_slug == "rain"


def test_roll_interval_from_constructor(weather_patch, fake_db):
    mgr = WorldWeatherManager(
        rules_model=always_rain(), seed=1, roll_interval_seconds=5
    )
    with patch.object(mgr, "advance_turn") as roll:
        for _ in range(12):
            mgr.update(1)
    assert roll.call_count == 2


def test_frame_updates_do_not_roll_every_frame(weather_patch, fake_db):
    mgr = WorldWeatherManager(rules_model=always_rain(), seed=1)
    with patch.object(mgr, "advance_turn") as roll:
        for _ in range(60 * 30):  # 30 s at 60 fps
            mgr.update(1 / 60)
    assert roll.call_count == 0


def test_advance_turn_ignores_interval(weather_patch, fake_db):
    mgr = WorldWeatherManager(rules_model=always_rain(), seed=1)
    mgr.advance_turn()
    assert mgr.current_slug == "rain"


# --- rule files --------------------------------------------------------------


def test_shipped_rules_file():
    model = load_weather_transition_rules(
        paths.mods_folder / "weather_previsions.yaml"
    )
    assert set(model.transitions) == set(WEATHER_SLUGS)
    assert model.roll_interval_seconds == 60


def test_flat_file_without_interval(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "sunny:\n  - next_slug: rain\n    trigger_chance: 0.5\n",
        encoding="utf-8",
    )
    model = load_weather_transition_rules(path)
    assert model.roll_interval_seconds == 60
    assert model.transitions["sunny"][0].next_slug == "rain"


def test_default_rules_missing_or_invalid(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "sunny:\n  - next_slug: rain\n    trigger_chance: 3\n",
        encoding="utf-8",
    )
    with patch("tuxemon.world.weather.logger") as log:
        assert load_default_weather_rules(tmp_path / "nope.yaml") is None
        assert load_default_weather_rules(bad) is None
    assert log.warning.call_count == 2
    assert "Weather will not change" in log.warning.call_args.args[0]


def _session_with(manager):
    return SimpleNamespace(client=SimpleNamespace(weather_manager=manager))


def test_load_weather_keeps_current_weather(weather_patch, fake_db):
    mgr = WorldWeatherManager(seed=1)
    mgr.set_weather("snow")
    mgr._elapsed_duration_seconds = 42.0
    session = _session_with(mgr)

    LoadWeatherAction().start(session)

    assert session.client.weather_manager is mgr
    assert mgr.current_slug == "snow"
    assert mgr.elapsed_time == 42.0
    assert mgr._transition_rules_model is not None
    assert "snow" in mgr._transition_rules_model.transitions


def test_load_weather_custom_file(weather_patch, fake_db, tmp_path):
    rules = tmp_path / "custom.yaml"
    rules.write_text(
        "roll_interval_seconds: 10\n"
        "sunny:\n  - next_slug: rain\n    trigger_chance: 1.0\n",
        encoding="utf-8",
    )
    mgr = WorldWeatherManager(seed=1)
    with patch("tuxemon.event.actions.load_weather.paths") as fake_paths:
        fake_paths.mods_folder = tmp_path
        LoadWeatherAction("custom.yaml").start(_session_with(mgr))
    assert mgr.roll_interval_seconds == 10
    assert mgr.current_slug == "sunny"


def test_load_weather_bad_file_keeps_rules(weather_patch, fake_db):
    mgr = WorldWeatherManager(rules_model=always_rain(), seed=1)
    with patch("tuxemon.event.actions.load_weather.logger") as log:
        LoadWeatherAction("does_not_exist.yaml").start(_session_with(mgr))
    assert mgr._transition_rules_model is not None
    assert "could not load" in log.warning.call_args.args[0]


# --- weather_is --------------------------------------------------------------


@pytest.mark.parametrize(
    "args,current,expected",
    [
        pytest.param(("rain",), "rain", True, id="single_match"),
        pytest.param(("rain",), "sunny", False, id="single_no_match"),
        pytest.param(
            ("rain", "thunderstorm"), "thunderstorm", True, id="multi_match"
        ),
        pytest.param(("rain,thunderstorm",), "rain", True, id="multi_one_arg"),
        pytest.param(
            ("rain", "thunderstorm"), "snow", False, id="multi_no_match"
        ),
    ],
)
def test_weather_is(fake_db, args, current, expected):
    session = _session_with(SimpleNamespace(current_slug=current))
    assert WeatherIsCondition(*args).test(session) is expected


def test_weather_is_without_manager(fake_db):
    session = SimpleNamespace(client=SimpleNamespace())
    assert WeatherIsCondition("rain").test(session) is False
    session = _session_with(None)
    assert WeatherIsCondition("rain").test(session) is False
    session = _session_with(SimpleNamespace(current_slug=None))
    assert WeatherIsCondition("rain").test(session) is False


def test_weather_is_unknown_slug(fake_db):
    session = _session_with(SimpleNamespace(current_slug="rain"))
    with patch("tuxemon.event.conditions.weather_is.logger") as log:
        assert WeatherIsCondition("rain", "acid_rain").test(session) is False
    assert "acid_rain" in log.warning.call_args.args[0]


# --- save / load -------------------------------------------------------------


def _fake_world(manager):
    world = MagicMock()
    world.client.weather_manager = manager
    world.faction_manager.set_state.return_value = {}
    world.menu_manager.menu_flags.export.return_value = {}
    return world


def test_save_and_restore_weather(weather_patch, fake_db):
    mgr = WorldWeatherManager(seed=1)
    mgr.set_weather("rain")
    mgr._elapsed_duration_seconds = 123.5

    saved = WorldState.get_state(_fake_world(mgr), MagicMock())
    data = saved.model_dump()
    assert data["weather_slug"] == "rain"
    assert data["weather_elapsed"] == 123.5

    new_mgr = WorldWeatherManager(seed=1)
    WorldState.set_state(
        _fake_world(new_mgr), MagicMock(), WorldSave.model_validate(data)
    )
    assert new_mgr.current_slug == "rain"
    assert new_mgr.elapsed_time == 123.5
    assert new_mgr.get_transition_history() == []


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            {"factions_manager": {}, "menu_flags": {}}, id="old_save"
        ),
        pytest.param({"weather_slug": None}, id="none_slug"),
        pytest.param(
            {"weather_slug": "lava", "weather_elapsed": 9.0}, id="unknown_slug"
        ),
    ],
)
def test_restore_falls_back_to_sunny(weather_patch, fake_db, data):
    mgr = WorldWeatherManager(seed=1)
    mgr.set_weather("snow")
    save = WorldSave.model_validate(data)
    WorldState.set_state(_fake_world(mgr), MagicMock(), save)
    assert mgr.current_slug == "sunny"
    assert mgr.elapsed_time == 0.0
    assert mgr.get_transition_history() == []
