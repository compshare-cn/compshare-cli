import base64

import pytest

from compshare_cli import parsing
from compshare_cli.errors import UsageError
from compshare_cli.parsing import (
    disk_gib,
    encode_password,
    memory_mib,
    money,
    money_cents,
    past_timestamp,
    timestamp,
)


def test_memory_and_disk_units() -> None:
    assert memory_mib("64GiB") == 64 * 1024
    assert memory_mib("65536MiB") == 64 * 1024
    assert disk_gib("100") == 100
    assert disk_gib("102400MiB") == 100


def test_invalid_sizes_raise_user_facing_errors() -> None:
    with pytest.raises(UsageError):
        memory_mib("100MiB")
    with pytest.raises(UsageError):
        disk_gib("3.5GiB")


def test_password_and_timestamp_encoding() -> None:
    assert encode_password("ucloud.cn") == base64.b64encode(b"ucloud.cn").decode("ascii")
    assert timestamp("1970-01-01T08:00:01+08:00") == 1
    assert timestamp("123") == 123


def test_relative_timestamp(monkeypatch) -> None:
    monkeypatch.setattr(parsing.time, "time", lambda: 1_000)
    assert timestamp("30m") == 2_800
    assert timestamp("2h") == 8_200
    assert timestamp("1d") == 87_400
    assert past_timestamp("30m") == -800
    assert past_timestamp("2h") == -6_200


def test_money_uses_exact_cents() -> None:
    assert str(money("123.45")) == "123.45"
    assert money_cents("123.45") == 12_345
    with pytest.raises(UsageError):
        money("1.001")
