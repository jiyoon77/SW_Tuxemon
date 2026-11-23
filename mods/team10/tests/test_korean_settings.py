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
