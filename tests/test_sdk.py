import json
import logging
from hashlib import sha1

import pytest
from ucloud.core import exc as ucloud_exc
from ucloud.core.transport import Response

from compshare_cli.config import Profile
from compshare_cli.errors import UsageError
from compshare_cli.sdk import CompShareSDK


def test_official_sdk_accepts_profile_configuration() -> None:
    sdk = CompShareSDK(Profile("public", "private"), "cn-wlcb")
    assert sdk._service.config.base_url == "https://api.compshare.cn"


def test_official_sdk_accepts_no_default_region() -> None:
    sdk = CompShareSDK(Profile("public", "private"))

    assert sdk._service.config.region is None


def test_official_sdk_accepts_base_url_override() -> None:
    sdk = CompShareSDK(
        Profile("public", "private"),
        base_url="https://insights.example.test",
    )

    assert sdk._service.config.base_url == "https://insights.example.test"


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


def test_sdk_invoke_does_not_mutate_the_callers_params(monkeypatch) -> None:
    class FakeService:
        def invoke(self, action, params):
            params["Action"] = action
            return {"RetCode": 0}

    sdk = object.__new__(CompShareSDK)
    sdk._service = FakeService()
    params = {"Region": "cn-wlcb"}

    sdk.invoke("DescribeCompShareInstance", params)

    assert params == {"Region": "cn-wlcb"}


@pytest.mark.parametrize("ids", [["uhost-1"], ["uhost-2", "uhost-1"]])
def test_monitor_sends_native_json_arrays_with_concatenated_signature(monkeypatch, ids) -> None:
    sdk = CompShareSDK(Profile("public", "private"), "cn-wlcb")
    captured = {}
    response = {"RetCode": 0, "Data": {"List": [], "PodList": []}}

    def send(request, **options):
        captured["request"] = request
        captured["options"] = options
        return Response(
            url=request.url,
            method=request.method,
            content=json.dumps(response).encode(),
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(sdk._service.transport, "send", send)
    params = {"Zone": "cn-wlcb-01", "UHostIds": ids}

    assert sdk.invoke("GetCompShareInstanceMonitor", params) == response
    assert params == {"Zone": "cn-wlcb-01", "UHostIds": ids}
    request = captured["request"]
    signing_text = (
        "ActionGetCompShareInstanceMonitorPublicKeypublicRegioncn-wlcbUHostIds"
        + "".join(ids)
        + "Zonecn-wlcb-01private"
    )
    assert request.json == {
        "Action": "GetCompShareInstanceMonitor",
        "Region": "cn-wlcb",
        "Zone": "cn-wlcb-01",
        "UHostIds": ids,
        "PublicKey": "public",
        "Signature": sha1(signing_text.encode()).hexdigest(),
    }
    assert request.data is None
    assert request.headers["Content-Type"] == "application/json"
    assert captured["options"]["timeout"] == sdk._service.config.timeout


@pytest.mark.parametrize("code", [171, 210, 230])
def test_monitor_preserves_api_errors_and_request_ids(monkeypatch, code) -> None:
    sdk = CompShareSDK(Profile("public", "private"), "cn-wlcb")
    errors = []
    sdk._service.middleware.exception(errors.append)
    monkeypatch.setattr(
        sdk._service.transport,
        "send",
        lambda *args, **kwargs: Response(
            url="https://api.compshare.cn",
            method="post",
            content=json.dumps({"RetCode": code, "Message": "monitor failure"}).encode(),
            headers={"Content-Type": "application/json", "X-UCLOUD-REQUEST-UUID": "request-1"},
        ),
    )

    with pytest.raises(ucloud_exc.RetCodeException) as raised:
        sdk.invoke("GetCompShareInstanceMonitor", {"UHostIds": ["uhost-1"]})

    assert raised.value.action == "GetCompShareInstanceMonitor"
    assert raised.value.code == code
    assert raised.value.request_uuid == "request-1"
    assert errors == [raised.value]


@pytest.mark.parametrize("ids", ["uhost-1", [1]])
def test_monitor_rejects_invalid_id_arrays(ids) -> None:
    sdk = CompShareSDK(Profile("public", "private"), "cn-wlcb")

    with pytest.raises(UsageError, match="UHostIds"):
        sdk.invoke("GetCompShareInstanceMonitor", {"UHostIds": ids})


def test_monitor_preserves_transport_failures(monkeypatch) -> None:
    sdk = CompShareSDK(Profile("public", "private"), "cn-wlcb")
    errors = []
    sdk._service.middleware.exception(errors.append)
    failure = TimeoutError("monitor request timed out")

    def send(*args, **kwargs):
        raise failure

    monkeypatch.setattr(sdk._service.transport, "send", send)

    with pytest.raises(TimeoutError) as raised:
        sdk.invoke("GetCompShareInstanceMonitor", {"UHostIds": ["uhost-1"]})

    assert raised.value is failure
    assert errors == [failure]


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
