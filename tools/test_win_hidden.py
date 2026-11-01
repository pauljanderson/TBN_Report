"""Hidden-console spawn helper. No network. No orders."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import win_hidden


def test_creationflags_hide_console_on_nt():
    flags = win_hidden.creationflags(new_group=True)
    if os.name == "nt":
        assert flags & win_hidden.CREATE_NO_WINDOW
        assert flags & win_hidden.CREATE_NEW_PROCESS_GROUP
        assert not (flags & win_hidden.DETACHED_PROCESS)
        assert not (flags & win_hidden.CREATE_NEW_CONSOLE)
    else:
        assert flags == 0


def test_startupinfo_hides_window_on_nt():
    info = win_hidden.startupinfo()
    if os.name != "nt":
        assert info is None
        return
    assert info is not None
    assert info.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert info.wShowWindow == win_hidden.SW_HIDE


def test_apply_hidden_strips_detached_and_new_console():
    kwargs = win_hidden._apply_hidden(
        {
            "creationflags": win_hidden.DETACHED_PROCESS | win_hidden.CREATE_NEW_CONSOLE,
            "cwd": ".",
        },
        new_group=True,
    )
    if os.name != "nt":
        assert "creationflags" not in kwargs
        return
    flags = kwargs["creationflags"]
    assert flags & win_hidden.CREATE_NO_WINDOW
    assert flags & win_hidden.CREATE_NEW_PROCESS_GROUP
    assert not (flags & win_hidden.DETACHED_PROCESS)
    assert not (flags & win_hidden.CREATE_NEW_CONSOLE)
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["startupinfo"].wShowWindow == win_hidden.SW_HIDE


def test_powershell_argv_asks_for_hidden_window():
    argv = win_hidden.powershell_argv("Get-Process")
    assert argv[0] == "powershell"
    assert "-WindowStyle" in argv
    assert argv[argv.index("-WindowStyle") + 1] == "Hidden"
    assert "-NoProfile" in argv


def test_popen_passes_hidden_flags(monkeypatch=None):
    captured = {}

    class Fake:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs

    saved = subprocess.Popen
    subprocess.Popen = Fake
    try:
        win_hidden.popen(["python", "-c", "pass"], new_group=True, cwd=".")
    finally:
        subprocess.Popen = saved
    kwargs = captured["kwargs"]
    if os.name == "nt":
        flags = kwargs["creationflags"]
        assert flags & win_hidden.CREATE_NO_WINDOW
        assert not (flags & win_hidden.DETACHED_PROCESS)
        assert not (flags & win_hidden.CREATE_NEW_CONSOLE)
        assert kwargs["startupinfo"].wShowWindow == win_hidden.SW_HIDE
    assert kwargs["stdin"] is subprocess.DEVNULL


if __name__ == "__main__":
    test_creationflags_hide_console_on_nt()
    test_startupinfo_hides_window_on_nt()
    test_apply_hidden_strips_detached_and_new_console()
    test_powershell_argv_asks_for_hidden_window()
    test_popen_passes_hidden_flags()
    print("ok")
