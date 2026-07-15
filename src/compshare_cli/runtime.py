from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from compshare_cli.config import DEFAULT_REGION, DEFAULT_ZONE, ConfigStore, Profile


@dataclass
class Runtime:
    json_output: bool = False
    profile_name: Optional[str] = None
    _profile: Optional[Profile] = None

    @property
    def profile(self) -> Profile:
        if self._profile is None:
            self._profile = ConfigStore().load_profile(self.profile_name)
        return self._profile

    @property
    def region(self) -> str:
        explicit = os.environ.get("COMPSHARE_REGION")
        if explicit:
            return explicit
        explicit_zone = os.environ.get("COMPSHARE_ZONE")
        if explicit_zone and "-" in explicit_zone:
            return explicit_zone.rsplit("-", 1)[0]
        return DEFAULT_REGION

    @property
    def zone(self) -> str:
        return os.environ.get("COMPSHARE_ZONE") or DEFAULT_ZONE
