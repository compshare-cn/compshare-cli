import logging

from compshare_cli.config import Profile
from compshare_cli.sdk import CompShareSDK


def test_official_sdk_accepts_profile_configuration() -> None:
    sdk = CompShareSDK(Profile("public", "private"), "cn-wlcb")
    assert sdk._service.config.base_url == "https://api.compshare.cn"


def test_sdk_uses_generic_invoke_and_quiet_logger(monkeypatch) -> None:
    captured = {}

    class FakeService:
        def invoke(self, action, params):
            captured["invoke"] = (action, params)
            return {"RetCode": 0}

    service = FakeService()

    class FakeClient:
        def __init__(self, config, logger):
            captured["config"] = config
            captured["logger"] = logger

        def ucompshare(self):
            return service

    monkeypatch.setattr("compshare_cli.sdk.Client", FakeClient)
    sdk = CompShareSDK(Profile("public", "private"), "cn-sh2")

    assert sdk.invoke("FutureCompShareAction", {"NewField": "value"}) == {"RetCode": 0}
    assert captured["invoke"] == ("FutureCompShareAction", {"NewField": "value"})
    assert captured["config"]["base_url"] == "https://api.compshare.cn"
    assert captured["config"]["region"] == "cn-sh2"
    assert captured["logger"].level == logging.CRITICAL
    assert captured["logger"].propagate is False


def test_sdk_download_uses_authenticated_service_transport(monkeypatch) -> None:
    captured = {}

    class Middleware:
        request_handlers = []
        exception_handlers = []

    class Config:
        ssl_verify = True
        ssl_cacert = None
        ssl_cert = None
        ssl_key = None
        timeout = 30
        max_retries = 2

    class Response:
        content = b"order,amount\n1,10\n"
        headers = {"Content-Type": "text/csv"}
        request_uuid = "request-1"

    class Transport:
        def send(self, request, **options):
            captured["request"] = request
            captured["options"] = options
            return Response()

    class FakeService:
        middleware = Middleware()
        config = Config()
        transport = Transport()

        def _build_http_request(self, params):
            captured["params"] = params
            return {"signed": True}

    service = FakeService()

    class FakeClient:
        def __init__(self, config, logger):
            pass

        def ucompshare(self):
            return service

    monkeypatch.setattr("compshare_cli.sdk.Client", FakeClient)
    sdk = CompShareSDK(Profile("public", "private"), "cn-wlcb")
    content, headers = sdk.download("DownloadTeamOrder", {"TeamId": 1001})

    assert content == b"order,amount\n1,10\n"
    assert headers["Content-Type"] == "text/csv"
    assert captured["params"] == {"Action": "DownloadTeamOrder", "TeamId": 1001}
    assert captured["request"] == {"signed": True}
    assert captured["options"]["max_retries"] == 2
