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
