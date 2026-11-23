# SPDX-License-Identifier: GPL-3.0
# team10: PR #12 review - changing the language must not touch other settings.
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tuxemon.config import TuxemonConfig


@pytest.fixture
def configs(tmp_path, monkeypatch):
    """A global CONFIG and a client.config copy, both on a temp file (not the user's)."""
    import tuxemon.states.set_language as set_language

    path = tmp_path / "tuxemon.yaml"
    global_config = TuxemonConfig(path)
    global_config.save_config()
    client_config = global_config.copy()  # what run_tuxemon.py does
    monkeypatch.setattr(set_language, "CONFIG", global_config, raising=False)  # development has no CONFIG here
    monkeypatch.setattr(set_language.T, "change_language", lambda locale: None)
    return path, global_config, client_config


def change_language(client_config, locale):
    from tuxemon.states.set_language import SetLanguage

    state = object.__new__(SetLanguage)
    state.main_menu = True  # language menu opened from the title screen
    state.client = SimpleNamespace(
        config=client_config,
        remove_state_by_name=lambda name: None,
        replace_state=lambda name, **kw: None,
    )
    SetLanguage.change_language(state, locale)


def test_language_change_keeps_other_settings(configs):
    path, global_config, client_config = configs
    # what the options menu does: change client.config and save
    client_config.config_model.gameplay.sound_volume = 0.4
    client_config.config_model.display.resolution_x = 768
    client_config.save_config()

    change_language(client_config, "ko_KR")

    saved = TuxemonConfig(path).config_model
    assert saved.game.locale == "ko_KR"
    assert saved.gameplay.sound_volume == 0.4
    assert saved.display.resolution_x == 768
    # the menus (global CONFIG) still switch to the Korean font right away
    assert global_config.locale.slug == "ko_KR"
    assert global_config.locale.font_file == "NanumGothic-Bold.ttf"


# --- PR #12 review 2: unit / hemisphere saved as translated text ------------------------

KOREAN = {
    "menu_units_metric": "미터법",
    "menu_units_imperial": "야드파운드법",
    "menu_hemisphere_north": "북반구",
    "menu_hemisphere_south": "남반구",
}


class _Slider:
    def set_onchange(self, callback):
        pass


class FakeMenu:
    """Records menu.add.* calls made by ControlState.initialize_items."""

    def __init__(self):
        self.selectors = {}
        self.add = self

    def select_widget(self, widget):
        pass

    def button(self, **kwargs):
        pass

    def range_slider(self, **kwargs):
        return _Slider()

    def selector(self, **kwargs):
        self.selectors[kwargs["selector_id"]] = kwargs

    def choose(self, selector_id, index):
        """Call onchange exactly like pygame-menu: onchange((item, index), *item[1:])."""
        kwargs = self.selectors[selector_id]
        item = kwargs["items"][index]
        kwargs["onchange"]((item, index), *item[1:])


@pytest.fixture
def options_menu(tmp_path, monkeypatch):
    import tuxemon.states.control_state as control_state

    path = tmp_path / "tuxemon.yaml"
    config = TuxemonConfig(path)
    config.config_model.game.locale = "ko_KR"
    config.config_model.gameplay.sound_volume = 0.4
    config.save_config()

    real_translate = control_state.T.translate
    monkeypatch.setattr(control_state.T, "translate", lambda key, *a, **k: KOREAN.get(key) or real_translate(key))

    state = object.__new__(control_state.ControlState)
    state.main_menu = False  # in-game options: unit and hemisphere are shown
    state.font_type = SimpleNamespace(small=10)
    state.client = SimpleNamespace(
        config=config,
        current_music=SimpleNamespace(muted=False),
        push_state=lambda *a, **k: None,
    )
    menu = FakeMenu()
    control_state.ControlState.initialize_items(state, menu)
    return path, menu


@pytest.mark.parametrize(
    "selector_id,index,field,expected",
    [
        ("unit", 1, "unit_measure", "imperial"),
        ("unit", 0, "unit_measure", "metric"),
        ("hemisphere", 1, "hemisphere", "southern"),
        ("hemisphere", 0, "hemisphere", "northern"),
    ],
)
def test_options_save_internal_value_not_translation(options_menu, selector_id, index, field, expected):
    path, menu = options_menu
    menu.choose(selector_id, index)

    saved = TuxemonConfig(path).config_model  # next game start
    assert getattr(saved.gameplay, field) == expected
    # and nothing else fell back to defaults
    assert saved.game.locale == "ko_KR"
    assert saved.gameplay.sound_volume == 0.4


def test_options_menu_still_shows_translations(options_menu):
    _, menu = options_menu
    labels = [item[0] for item in menu.selectors["unit"]["items"] + menu.selectors["hemisphere"]["items"]]
    assert labels == ["미터법", "야드파운드법", "북반구", "남반구"]


# --- weather options from PR #7 must keep working next to the fix above ----------------


@pytest.mark.parametrize("selector_id", ["time_tint", "weather_effects"])
def test_weather_options_still_save(options_menu, selector_id):
    path, menu = options_menu
    assert menu.selectors[selector_id]["default"] == 0  # on by default
    menu.choose(selector_id, 1)  # off
    saved = TuxemonConfig(path).config_model
    assert getattr(saved.graphics, selector_id) is False
    assert saved.game.locale == "ko_KR"
    menu.choose(selector_id, 0)  # back on
    assert getattr(TuxemonConfig(path).config_model.graphics, selector_id) is True
