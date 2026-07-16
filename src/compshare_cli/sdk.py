from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from ucloud.client import Client
from ucloud.core import exc as ucloud_exc
from ucloud.core.transport import SSLOption

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

    def download(self, action: str, params: Dict[str, Any]) -> Tuple[bytes, Dict[str, str]]:
        """Invoke an authenticated action whose success response is a file stream."""
        args = dict(params)
        args["Action"] = action
        for handler in self._service.middleware.request_handlers:
            args = handler(args)
        request = self._service._build_http_request(args)
        try:
            response = self._service.transport.send(
                request,
                ssl_option=SSLOption(
                    self._service.config.ssl_verify,
                    self._service.config.ssl_cacert,
                    self._service.config.ssl_cert,
                    self._service.config.ssl_key,
                ),
                timeout=self._service.config.timeout,
                max_retries=self._service.config.max_retries,
            )
        except Exception as error:
            for handler in self._service.middleware.exception_handlers:
                handler(error)
            raise

        content_type = str(response.headers.get("Content-Type", "")).lower()
        if "json" in content_type:
            data = response.json() or {}
            if int(data.get("RetCode", -1)) != 0:
                error = ucloud_exc.RetCodeException(
                    action=action,
                    code=int(data.get("RetCode", 0)),
                    message=data.get("Message", ""),
                    request_uuid=response.request_uuid,
                )
                for handler in self._service.middleware.exception_handlers:
                    handler(error)
                raise error
        return response.content, {str(key): str(value) for key, value in response.headers.items()}
