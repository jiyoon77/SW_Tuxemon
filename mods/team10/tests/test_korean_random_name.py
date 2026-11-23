# SPDX-License-Identifier: GPL-3.0
# team10: PR #12 review 4 - "random name" in the name input must not crash in Korean.
from __future__ import annotations

from types import SimpleNamespace

import pytest


def pick_random(monkeypatch, current_language, config_slug, gender="male"):
    """Run the real InputMenu.pick_random with the real npc_names.yaml."""
    import tuxemon.states.input as input_state
    from tuxemon.menu.input import NameDataLoader

    monkeypatch.setattr(input_state.T, "get_current_language", lambda: current_language)
    monkeypatch.setattr(input_state.local_session, "_player", SimpleNamespace(gender=gender), raising=False)

    picked = {}
    menu = object.__new__(input_state.InputMenu)
    menu.name_loader = NameDataLoader("npc_names.yaml")
    menu.client = SimpleNamespace(config=SimpleNamespace(locale=SimpleNamespace(slug=config_slug)))
    menu.input_controller = SimpleNamespace(set_string=lambda s: picked.setdefault("name", s))
    menu.update_text_area = lambda: None
    menu.update_char_counter = lambda: None
    input_state.InputMenu.pick_random(menu)
    return picked.get("name")


@pytest.mark.parametrize("gender", ["male", "female", "neutral"])
def test_random_name_in_korean(monkeypatch, gender):
    name = pick_random(monkeypatch, "ko_KR", "ko_KR", gender)
    assert isinstance(name, str) and name


def test_random_name_in_english_still_works(monkeypatch):
    assert pick_random(monkeypatch, "en_US", "en_US")


def test_random_name_in_korean_is_korean(monkeypatch):
    name = pick_random(monkeypatch, "ko_KR", "ko_KR", "female")
    assert all("가" <= ch <= "힣" for ch in name)


def test_language_without_names_falls_back_to_english(monkeypatch):
    """A future language with no npc_names.yaml entry must not crash."""
    import yaml

    from tuxemon.constants import paths

    with open(paths.mods_folder / "npc_names.yaml", encoding="utf-8") as f:
        english = yaml.safe_load(f)["random_names"]["en_us"]["male"]
    assert pick_random(monkeypatch, "xx_XX", "xx_XX", "male") in english
