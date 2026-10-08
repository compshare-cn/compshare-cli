from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from ucloud.client import Client
from ucloud.core import exc as ucloud_exc
from ucloud.core.transport import Response, SSLOption

from compshare_cli.config import Profile
from compshare_cli.errors import UsageError
from compshare_cli.i18n import tr


class CompShareSDK:
    """Thin adapter around the official UCloud Python SDK.

    The generic invoke path is intentional. Generated UCompShare request schemas can
    lag behind the public API and silently discard newer fields.
    """

    def __init__(
        self,
        profile: Profile,
        region: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        logger = logging.getLogger("compshare_cli.ucloud")
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False
        config = profile.sdk_config(region)
        if base_url is not None:
            config["base_url"] = base_url
        self._service = Client(config, logger=logger).ucompshare()

    def invoke(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if action == "GetCompShareInstanceMonitor":
            return self._json_response(action, self._send_request(action, params))
        return self._service.invoke(action, dict(params))

    def download(self, action: str, params: Dict[str, Any]) -> Tuple[bytes, Dict[str, str]]:
        """Invoke an authenticated action whose success response is a file stream."""
        response = self._send_request(action, params)
        if "json" in str(response.headers.get("Content-Type", "")).lower():
            self._json_response(action, response)
        return response.content, {str(key): str(value) for key, value in response.headers.items()}

    def _send_request(self, action: str, params: Dict[str, Any]) -> Response:
        args = dict(params)
        args["Action"] = action
        for handler in self._service.middleware.request_handlers:
            args = handler(args)
        monitoring = action == "GetCompShareInstanceMonitor"
        instance_ids = args.get("UHostIds")
        if monitoring and instance_ids is not None:
            if not isinstance(instance_ids, list) or any(
                not isinstance(identifier, str) for identifier in instance_ids
            ):
                raise UsageError(tr("Monitoring requires UHostIds to be an array of strings."))
            # This endpoint signs native JSON arrays by concatenating their elements.
            args["UHostIds"] = "".join(instance_ids)
        request = self._service._build_http_request(args)
        if monitoring:
            request.json = dict(request.data)
            if instance_ids is not None:
                request.json["UHostIds"] = list(instance_ids)
            request.data = None
            request.headers["Content-Type"] = "application/json"
        try:
            return self._service.transport.send(
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

    def _json_response(self, action: str, response: Response) -> Dict[str, Any]:
        try:
            data = response.json() or {}
        except Exception as error:
            for handler in self._service.middleware.exception_handlers:
                handler(error)
            raise
        for handler in self._service.middleware.response_handlers:
            data = handler(data, response)
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
        return data
