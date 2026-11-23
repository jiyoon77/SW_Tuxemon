# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2014-2026 William Edwards <shadowapex@gmail.com>, Benjamin Bean <superman2k5@gmail.com>
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import final

from tuxemon.constants import paths
from tuxemon.event.eventaction import EventAction
from tuxemon.session import Session
from tuxemon.world.weather import (
    DEFAULT_WEATHER_RULES_FILE,
    load_weather_transition_rules,
)

logger = logging.getLogger(__name__)


@final
@dataclass
class LoadWeatherAction(EventAction):
    """
    Loads a YAML file containing weather previsions using the Pydantic schema
    and registers it with the WorldWeatherManager.

    The current weather and its elapsed time are kept; only the transition
    rules (and the roll interval) are replaced.

    Script usage:
        .. code-block::

            load_weather [<path_to_yaml_file>]

    Script parameters:
        model_file: Path to the YAML file, relative to the mods folder.
            Defaults to "weather_previsions.yaml".
    """

    name = "load_weather"
    model_file: str | None = None

    def start(self, session: Session) -> None:
        filename = self.model_file or DEFAULT_WEATHER_RULES_FILE
        yaml_path = paths.mods_folder / filename

        try:
            rules_model = load_weather_transition_rules(yaml_path)
        except Exception as exc:
            logger.warning(
                f"load_weather: could not load '{yaml_path}': {exc}"
            )
            return

        session.client.weather_manager.load_rules_model(rules_model)
        logger.info(f"Weather rules loaded from '{yaml_path}'.")
