#!/usr/bin/env python3
"""Run independent DailyRun system bats together and collect exit codes.

Each job is one line in --jobs-file:

    step;LABEL;run_something.bat;drive\\LABEL_profile.duckdb

The fourth field is optional. When present it is exported as TBN_INSTRUMENT_DB
so rocket_tbn writes a per-system timing database instead of sharing
drive/brt_profile.duckdb.

At most 8 system engines run at once. A longer list starts as slots free, not all
at once. Nothing already running is killed to get under that cap. Before each
start, if Win32_Processor LoadPercentage is above 90, this waits and retries.
If one job fails, the others keep running; this process exits 1 after every job
has finished.
Does not launch engines by itself; it only calls the bats named in the jobs file.

    python tools/dailyrun_wave.py --self-check
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAX_SYSTEMS_AT_ONCE = 8
CPU_LOAD_WAIT_ABOVE = 90.0
CPU_POLL_SEC = 15.0
SLOT_POLL_SEC = 2.0


def _log(fp, line: str) -> None:
    text = line if line.endswith("\n") else line + "\n"
    sys.stdout.write(text)
    sys.stdout.flush()
    if fp is not None:
        fp.write(text)
        fp.flush()


def format_captured_line(raw: bytes, label: str) -> str | None:
    """One log line. Strip CR so a text-mode log does not store ``\\r\\r\\n``.

    Windows pipes often deliver ``\\r\\n``. Appending that string to a text
    file turns the ``\\n`` into another ``\\r\\n`` and leaves the original
    ``\\r``, which readers then count as a second blank line.
    """
    text = raw.decode("utf-8", errors="replace").replace("\r", "")
    if text == "":
        return None
    if not text.endswith("\n"):
        text += "\n"
    return f"[{label}] {text}"


def _pump(proc: subprocess.Popen, label: str, fp, lock: threading.Lock) -> None:
    stdout = proc.stdout
    if stdout is None:
        return
    for raw in stdout:
        line = format_captured_line(raw, label)
        if line is None:
            continue
        with lock:
            if fp is not None:
                fp.write(line)
                fp.flush()


def _parse_jobs(path: Path) -> list[tuple[str, str, Path, str]]:
    jobs: list[tuple[str, str, Path, str]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(";")
        if len(parts) not in (3, 4):
            raise SystemExit(f"jobs file {path}:{lineno}: expected step;LABEL;bat;instrument-db")
        step, label, bat = parts[0].strip(), parts[1].strip(), parts[2].strip()
        instrument = parts[3].strip() if len(parts) == 4 else ""
        if not step or not label or not bat:
            raise SystemExit(f"jobs file {path}:{lineno}: blank field")
        if any(sep in bat for sep in ("\\", "/", ":")) or bat != Path(bat).name:
            raise SystemExit(f"jobs file {path}:{lineno}: bat must be a file name, got {bat}")
        if not bat.lower().startswith("run_") or not bat.lower().endswith(".bat"):
            raise SystemExit(f"jobs file {path}:{lineno}: refusing non run_*.bat ({bat})")
        bat_path = (ROOT / bat).resolve()
        if bat_path.parent != ROOT or not bat_path.is_file():
            raise SystemExit(f"jobs file {path}:{lineno}: missing {bat_path}")
        jobs.append((step, label, bat_path, instrument))
    if not jobs:
        raise SystemExit(f"jobs file {path} has no jobs")
    return jobs


def start_blocked(running: int, cpu_load: float | None) -> str | None:
    """Reason to wait before launching another system, or None if a start is allowed.

    Does not stop a process that is already running.
    ``cpu_load`` is Win32_Processor LoadPercentage (highest, if several).
    A missing reading blocks the next start so we retry instead of guessing.
    """
    if running >= MAX_SYSTEMS_AT_ONCE:
        return f"{running} already running (cap {MAX_SYSTEMS_AT_ONCE})"
    if cpu_load is None:
        return "CPU LoadPercentage unreadable"
    if cpu_load > CPU_LOAD_WAIT_ABOVE:
        return f"CPU LoadPercentage {cpu_load:.0f}% > {CPU_LOAD_WAIT_ABOVE:.0f}"
    return None


def cpu_load_percentage() -> float | None:
    """Highest Win32_Processor LoadPercentage, or None if the query fails."""
    script = (
        "$vals = @(Get-CimInstance -ClassName Win32_Processor | "
        "ForEach-Object { $_.LoadPercentage } | Where-Object { $_ -ne $null }); "
        "if (-not $vals) { exit 2 }; "
        "($vals | Measure-Object -Maximum).Maximum"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return None


def _reap(
    running: list[tuple[str, str, subprocess.Popen, float, threading.Thread]],
    log_fp,
) -> bool:
    """Record systems that have already exited. Does not stop the ones still running."""
    failed = False
    still: list[tuple[str, str, subprocess.Popen, float, threading.Thread]] = []
    for step, label, proc, started, reader in running:
        code = proc.poll()
        if code is None:
            still.append((step, label, proc, started, reader))
            continue
        reader.join(timeout=5)
        elapsed = time.perf_counter() - started
        _log(log_fp, f"[{step}] DONE {label}  exit={code}  elapsed={elapsed:.1f}s")
        if code != 0:
            failed = True
    running[:] = still
    return failed


def _start_one(
    job: tuple[str, str, Path, str],
    log_fp,
    lock: threading.Lock,
) -> tuple[str, str, subprocess.Popen, float, threading.Thread]:
    step, label, bat_path, instrument = job
    env = os.environ.copy()
    env["DAILYRUN_WAVE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if instrument:
        env["TBN_INSTRUMENT_DB"] = instrument
    _log(log_fp, f"[{step}] START {label}  {bat_path.name}")
    proc = subprocess.Popen(
        ["cmd.exe", "/d", "/c", "call", str(bat_path)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    reader = threading.Thread(target=_pump, args=(proc, label, log_fp, lock), daemon=True)
    reader.start()
    return (step, label, proc, time.perf_counter(), reader)


def run_jobs(jobs: list[tuple[str, str, Path, str]], log_path: Path | None) -> int:
    log_fp = None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fp = log_path.open("a", encoding="utf-8")
    lock = threading.Lock()
    pending = list(jobs)
    running: list[tuple[str, str, subprocess.Popen, float, threading.Thread]] = []
    failed = False
    slot_note = False
    try:
        names = ", ".join(label for _step, label, _bat, _inst in jobs)
        _log(
            log_fp,
            f"[wave] queued {len(jobs)} ({names}); "
            f"at most {MAX_SYSTEMS_AT_ONCE} at once; "
            f"wait if CPU LoadPercentage > {CPU_LOAD_WAIT_ABOVE:.0f}",
        )
        while pending or running:
            if _reap(running, log_fp):
                failed = True
            if not pending:
                if running:
                    time.sleep(SLOT_POLL_SEC)
                continue
            _step, label, _bat, _inst = pending[0]
            if len(running) >= MAX_SYSTEMS_AT_ONCE:
                if not slot_note:
                    _log(
                        log_fp,
                        f"[wave] waiting: {len(running)} already running "
                        f"(cap {MAX_SYSTEMS_AT_ONCE}); not starting {label}",
                    )
                    slot_note = True
                time.sleep(SLOT_POLL_SEC)
                continue
            slot_note = False
            cpu = cpu_load_percentage()
            reason = start_blocked(len(running), cpu)
            if reason:
                _log(log_fp, f"[wave] waiting: {reason}; not starting {label}")
                time.sleep(CPU_POLL_SEC)
                continue
            started = _start_one(pending.pop(0), log_fp, lock)
            running.append(started)
            step_s, label_s = started[0], started[1]
            _log(
                log_fp,
                f"[{step_s}] {label_s} live={len(running)} queued={len(pending)}",
            )
        if failed:
            _log(log_fp, "[wave] FAILED — one or more systems exited non-zero (siblings were not killed)")
            return 1
        _log(log_fp, "[wave] all systems exited 0")
        return 0
    finally:
        if log_fp is not None:
            log_fp.close()


def _self_check() -> int:
    """Check the start cap. Does not call a system bat or start a backtest."""
    checks = [
        (start_blocked(8, 10.0) is not None, "8 running must wait"),
        (start_blocked(7, 91.0) is not None, "CPU 91 must wait"),
        (start_blocked(7, 90.0) is None, "CPU 90 may start"),
        (start_blocked(0, 90.0) is None, "idle CPU 90 may start"),
        (start_blocked(3, None) is not None, "unreadable CPU must wait"),
        (start_blocked(9, 1.0) is not None, "over cap must wait"),
        (
            format_captured_line(b"Zones written: x\r\n", "WPBR")
            == "[WPBR] Zones written: x\n",
            "strip CR so the log does not double each line",
        ),
    ]
    bad = False
    for ok, note in checks:
        print(f"[self-check] {'ok' if ok else 'FAIL'} {note}")
        if not ok:
            bad = True
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run DailyRun system bats together.")
    ap.add_argument("--log", default="", help="Append start/exit lines and engine output here.")
    ap.add_argument("--jobs-file", default="", help="step;LABEL;run_x.bat;instrument_db lines.")
    ap.add_argument("--self-check", action="store_true", help="Wait on cmd exit codes only.")
    ap.add_argument("--list", action="store_true", help="Print parsed jobs and exit. Does not start them.")
    args = ap.parse_args(argv)
    if args.self_check:
        return _self_check()
    if not args.jobs_file:
        ap.error("--jobs-file is required unless --self-check")
    jobs = _parse_jobs(Path(args.jobs_file))
    if args.list:
        for step, label, bat_path, instrument in jobs:
            print(f"{step} {label} {bat_path.name} {instrument}")
        return 0
    log_path = Path(args.log) if args.log else None
    return run_jobs(jobs, log_path)


if __name__ == "__main__":
    raise SystemExit(main())
