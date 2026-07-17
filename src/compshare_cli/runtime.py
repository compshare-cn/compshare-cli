from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from compshare_cli.config import ConfigStore, Profile


@dataclass
class Runtime:
    json_output: bool = False
    profile_name: Optional[str] = None
    show_sensitive: bool = False
    _profile: Optional[Profile] = None

    @property
    def profile(self) -> Profile:
        if self._profile is None:
            self._profile = ConfigStore().load_profile(self.profile_name)
        return self._profile
