from __future__ import annotations

import logging
from typing import Any, Dict

from ucloud.client import Client

from compshare_cli.config import Profile


class CompShareSDK:
    """Thin adapter around the official UCloud Python SDK.

    The generic invoke path is intentional. Generated UCompShare request schemas can
    lag behind the public API and silently discard newer fields.
    """

    def __init__(self, profile: Profile, region: str) -> None:
        logger = logging.getLogger("compshare_cli.ucloud")
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False
        self._service = Client(profile.sdk_config(region), logger=logger).ucompshare()

    def invoke(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._service.invoke(action, params)
