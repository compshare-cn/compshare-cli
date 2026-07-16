from compshare_cli import api
from compshare_cli.config import Profile
from compshare_cli.runtime import Runtime


def test_collect_pages_fetches_until_total(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append(params)
        offset = params["Offset"]
        rows = [{"Id": index} for index in range(offset, min(offset + params["Limit"], 205))]
        return {"TotalCount": 205, "Items": rows}

    monkeypatch.setattr(api, "call", fake_call)
    response = api.collect_pages(Runtime(), "ListItems", {"Region": "cn-a"}, "Items")

    assert len(response["Items"]) == 205
    assert [call["Offset"] for call in calls] == [0, 100, 200]
    assert [call["Limit"] for call in calls] == [100, 100, 100]


def test_collect_pages_honors_requested_range(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append(params)
        return {"TotalCount": 200, "Items": [{"Id": index} for index in range(20)]}

    monkeypatch.setattr(api, "call", fake_call)
    response = api.collect_pages(
        Runtime(),
        "ListItems",
        {},
        "Items",
        offset=10,
        limit=20,
    )

    assert response["ReturnedCount"] == 20
    assert calls == [{"Limit": 20, "Offset": 10}]


def test_collect_pages_accepts_null_list(monkeypatch) -> None:
    monkeypatch.setattr(api, "call", lambda *args, **kwargs: {"TotalCount": 0, "Items": None})
    response = api.collect_pages(Runtime(), "ListItems", {}, "Items")

    assert response["Items"] == []
    assert response["ReturnedCount"] == 0


def test_collect_pages_accepts_total_field(monkeypatch) -> None:
    calls = []

    def fake_call(state, action, params):
        calls.append(params)
        return {"Total": 100, "Items": [{"Id": index} for index in range(100)]}

    monkeypatch.setattr(api, "call", fake_call)
    response = api.collect_pages(Runtime(), "ListItems", {}, "Items")

    assert response["ReturnedCount"] == 100
    assert len(calls) == 1


def test_invoke_accepts_null_list_in_human_output(monkeypatch, capsys) -> None:
    class FakeSDK:
        def __init__(self, profile, region):
            pass

        def invoke(self, action, params):
            return {"Items": None}

    monkeypatch.setenv("COMPSHARE_LANG", "en")
    monkeypatch.setattr(api, "CompShareSDK", FakeSDK)
    response = api.invoke(
        Runtime(_profile=Profile("public", "private")),
        "ListItems",
        {},
        list_key="Items",
        columns=(("Id", "ID"),),
    )

    assert response == {"Items": None}
    assert "No results" in capsys.readouterr().out
