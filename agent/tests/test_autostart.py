"""Autostart: plist content, Windows registry seam, target resolution."""

import plistlib
import sys
from io import BytesIO

import pytest

from djutil_agent.platform import autostart


def test_target_args_dev(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    assert autostart._target_args() == [
        "/usr/bin/python3",
        "-m",
        "djutil_agent",
        "tray",
    ]


def test_target_args_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\DJUtil Agent.exe")
    assert autostart._target_args() == [r"C:\Apps\DJUtil Agent.exe", "tray"]


def test_plist_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "_logs_dir", lambda: tmp_path / "logs")
    d = autostart._plist_dict()
    assert d["Label"] == autostart.PLIST_LABEL
    assert d["RunAtLoad"] is True
    assert d["KeepAlive"] is False
    args = d["ProgramArguments"]
    assert isinstance(args, list) and args[-1] == "tray"
    assert "autostart.out.log" in str(d["StandardOutPath"])
    # must be valid plist content
    buf = BytesIO()
    plistlib.dump(d, buf)
    buf.seek(0)
    assert plistlib.load(buf)["Label"] == autostart.PLIST_LABEL


class _FakeKey:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 1
    REG_SZ = 1

    def __init__(self):
        self.store = {}

    def OpenKey(self, hive, sub, reserved=0, access=0):
        assert hive == self.HKEY_CURRENT_USER
        return _FakeKey(self.store)

    def SetValueEx(self, key, name, reserved, type_, value):
        key.store[name] = value

    def QueryValueEx(self, key, name):
        if name not in key.store:
            raise OSError("not found")
        return key.store[name], self.REG_SZ

    def DeleteValue(self, key, name):
        if name not in key.store:
            raise OSError("not found")
        del key.store[name]


@pytest.fixture()
def fake_winreg(monkeypatch):
    fake = _FakeWinreg()
    monkeypatch.setattr(autostart, "_winreg", lambda: fake)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Python312\python.exe")
    return fake


def test_windows_enable_status_disable(fake_winreg):
    autostart.enable()
    value = fake_winreg.store[autostart.RUN_VALUE]
    assert "djutil_agent" in value and "tray" in value
    assert autostart.is_enabled()
    assert autostart.status_value() == value
    autostart.disable()
    assert not autostart.is_enabled()
    assert autostart.status_value() is None


def test_windows_value_uses_exe_when_frozen(fake_winreg, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\DJUtil Agent.exe")
    autostart.enable()
    assert fake_winreg.store[autostart.RUN_VALUE].startswith(
        '"C:\\Apps\\DJUtil Agent.exe"'
    )
    assert fake_winreg.store[autostart.RUN_VALUE].endswith("tray")
