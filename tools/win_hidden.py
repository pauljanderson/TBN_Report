"""Spawn subprocesses on Windows without a visible console or focus steal.

python.exe and powershell.exe are console apps. A bare Popen, run, or
check_output opens a Command Prompt (or Windows Terminal tab) that grabs
the keyboard. CREATE_NO_WINDOW (0x08000000) plus STARTUPINFO SW_HIDE
avoids that. Stdout/stderr stay on the redirected files or pipes the
caller already set.

Do not use CREATE_NEW_CONSOLE. Do not combine DETACHED_PROCESS with
CREATE_NO_WINDOW — Windows then ignores CREATE_NO_WINDOW and still
allocates a visible console.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
DETACHED_PROCESS = 0x00000008
CREATE_NEW_CONSOLE = 0x00000010
SW_HIDE = 0


def creationflags(*, new_group: bool = False) -> int:
    if os.name != "nt":
        return 0
    flags = CREATE_NO_WINDOW
    if new_group:
        flags |= CREATE_NEW_PROCESS_GROUP
    return flags


def startupinfo() -> subprocess.STARTUPINFO | None:
    if os.name != "nt":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = SW_HIDE
    return info


def _apply_hidden(kwargs: dict[str, Any], *, new_group: bool) -> dict[str, Any]:
    kwargs = dict(kwargs)
    if os.name != "nt":
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        return kwargs
    flags = int(kwargs.pop("creationflags", 0) or 0)
    flags |= creationflags(new_group=new_group)
    flags &= ~DETACHED_PROCESS
    flags &= ~CREATE_NEW_CONSOLE
    kwargs["creationflags"] = flags
    kwargs.setdefault("startupinfo", startupinfo())
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return kwargs


def popen(argv, *, new_group: bool = False, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(argv, **_apply_hidden(kwargs, new_group=new_group))


def run(argv, *, new_group: bool = False, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, **_apply_hidden(kwargs, new_group=new_group))


def check_output(argv, *, new_group: bool = False, **kwargs):
    return subprocess.check_output(argv, **_apply_hidden(kwargs, new_group=new_group))


def powershell_argv(command: str) -> list[str]:
    """Hidden PowerShell. -WindowStyle Hidden plus CREATE_NO_WINDOW."""
    return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command]
