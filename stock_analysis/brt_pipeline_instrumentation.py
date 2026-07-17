"""
End-to-end BRT run timing, unified pipeline progress, and optional DuckDB persistence.

Used by rocket_brt.py to measure every major phase (load, backtest, yfinance, enrichment, writes).
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional


def _format_eta_remaining(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h, rem = divmod(s, 3600)
    return f"{h}h {rem // 60}m"


class BRTPipelineInstrument:
    """Tracks phase wall times, weighted pipeline progress, and optional DuckDB/CSV export."""

    def __init__(
        self,
        enabled: bool = True,
        output_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
        run_id: Optional[str] = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.output_dir = Path(output_dir) if output_dir else None
        self.db_path = Path(db_path) if db_path else None
        self.run_id = run_id or (datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
        self.started_at = time.perf_counter()
        self._phase_seconds: dict[str, float] = {}
        self._phase_active: dict[str, float] = {}
        self._current_phase = ""
        self._total_units = 0
        self._done_units = 0
        self._backtest_units = 0
        self._backtest_done = 0
        self._post_unit_budget: dict[str, int] = {}
        self._post_unit_done: dict[str, int] = {}
        self._meta: dict[str, Any] = {}
        self._progress_t0: Optional[float] = None
        self._last_progress_line = ""
        self._last_logged_line = ""

    def set_meta(self, **kwargs: Any) -> None:
        self._meta.update(kwargs)

    def configure_backtest(self, n_symbols: int) -> None:
        """Backtest contributes one progress unit per symbol."""
        n = max(0, int(n_symbols))
        self._backtest_units = n
        self._backtest_done = 0
        self._total_units = self._backtest_units + sum(self._post_unit_budget.values())
        self._sync_done_units()
        self._progress_t0 = time.perf_counter()
        if self.enabled and n > 0:
            print(f"[PIPELINE] Planned units: backtest={n} (+ post phases added after backtest)", flush=True)

    def add_post_units(self, **weights: int) -> None:
        """Register post-backtest work units (yfinance, entry_indicators, writes, …)."""
        for k, v in weights.items():
            w = max(0, int(v))
            if w > 0:
                self._post_unit_budget[k] = w
                self._meta[f"units_{k}"] = w
        self._total_units = self._backtest_units + sum(self._post_unit_budget.values())
        self._sync_done_units()
        if self.enabled and weights:
            parts = ", ".join(f"{k}={int(v)}" for k, v in sorted(weights.items()) if int(v) > 0)
            print(f"[PIPELINE] Post-run units: {parts} (pipeline total={self._total_units})", flush=True)
            self._print_progress("post-run planned")

    def mark_backtest_complete(self) -> None:
        """Call when all symbols finished; keeps backtest slice at 100% before post phases advance."""
        if not self.enabled or self._backtest_units <= 0:
            return
        self._backtest_done = self._backtest_units
        self._sync_done_units()
        self._print_progress(f"backtest {self._backtest_done}/{self._backtest_units}")

    def _sync_done_units(self) -> None:
        self._done_units = min(
            self._total_units,
            self._backtest_done + sum(self._post_unit_done.values()),
        )

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        prev = self._current_phase
        self._current_phase = name
        t0 = time.perf_counter()
        self._phase_active[name] = t0
        try:
            yield
        finally:
            dt = time.perf_counter() - t0
            self._phase_seconds[name] = self._phase_seconds.get(name, 0.0) + dt
            self._phase_active.pop(name, None)
            self._current_phase = prev

    def backtest_tick(self, done: int, total: int) -> None:
        if not self.enabled or total <= 0:
            return
        self._backtest_done = min(done, self._backtest_units)
        self._sync_done_units()
        self._print_progress(f"backtest {done}/{total}")

    def post_tick(self, phase: str, done: int, total: int) -> None:
        """Advance global progress during a post phase (maps local done/total to global units)."""
        if not self.enabled or total <= 0:
            return
        budget = self._post_unit_budget.get(phase, max(1, total))
        self._post_unit_done[phase] = min(budget, int(budget * done / float(total)))
        self._sync_done_units()
        self._print_progress(f"{phase} {done}/{total}")

    def complete_phase_units(self, phase: str) -> None:
        """Mark all units for a fixed-weight post phase as done."""
        budget = self._post_unit_budget.get(phase, 1)
        self._post_unit_done[phase] = budget
        self._sync_done_units()
        self._print_progress(phase)

    def _print_progress(self, detail: str) -> None:
        total = max(1, self._total_units)
        done = min(self._done_units, total)
        pct = 100.0 * done / total
        eta_part = ""
        t0 = self._progress_t0
        if t0 is not None and 0 < done < total:
            elapsed = time.perf_counter() - t0
            if elapsed > 0:
                remaining_s = (total - done) * (elapsed / float(done))
                rem_str = _format_eta_remaining(remaining_s)
                now = datetime.now()
                finish_at = now + timedelta(seconds=remaining_s)
                if finish_at.date() == now.date():
                    done_clock = finish_at.strftime("%H:%M:%S")
                else:
                    done_clock = finish_at.strftime("%Y-%m-%d %H:%M")
                eta_part = f"  ~{rem_str} left (done ~{done_clock})"
        msg = f"[PIPELINE] {detail}  overall {done}/{total} ({pct:.1f}%){eta_part}"
        self._last_progress_line = msg
        out = sys.stdout
        if out.isatty():
            try:
                cols = max(40, shutil.get_terminal_size().columns)
            except OSError:
                cols = 120
            pad = max(0, (cols - 1) - len(msg))
            out.write("\r" + msg + " " * pad)
        else:
            if msg != getattr(self, "_last_logged_line", ""):
                out.write(msg + "\n")
                self._last_logged_line = msg
        out.flush()

    def end_progress_line(self) -> None:
        if self.enabled and sys.stdout.isatty() and self._last_progress_line:
            print(file=sys.stdout, flush=True)

    def record_phase_seconds(self, name: str, seconds: float) -> None:
        if seconds > 0:
            self._phase_seconds[name] = self._phase_seconds.get(name, 0.0) + float(seconds)

    def finish(self) -> dict[str, float]:
        """Print summary, write CSV/JSON, optional DuckDB. Returns phase -> seconds."""
        if not self.enabled:
            return dict(self._phase_seconds)
        self.end_progress_line()
        total_run = time.perf_counter() - self.started_at
        phases = dict(sorted(self._phase_seconds.items(), key=lambda kv: -kv[1]))
        print(f"\n[PIPELINE] Run {self.run_id} finished in {total_run:.1f}s", flush=True)
        if phases:
            print("[PIPELINE] Phase timings (slowest first):", flush=True)
            for name, sec in phases.items():
                pct = 100.0 * sec / total_run if total_run > 0 else 0.0
                print(f"  {name:28s} {sec:8.2f}s  ({pct:5.1f}%)", flush=True)
        else:
            print("[PIPELINE] (no phase timings recorded)", flush=True)
        self._write_artifacts(phases, total_run)
        return phases

    def _write_artifacts(self, phases: dict[str, float], total_run: float) -> None:
        if self.output_dir is None:
            return
        out = self.output_dir
        out.mkdir(parents=True, exist_ok=True)
        ts = self.run_id
        rows = [{"phase": k, "seconds": v, "pct_of_run": (100.0 * v / total_run if total_run > 0 else 0.0)} for k, v in phases.items()]
        try:
            import pandas as pd

            pd.DataFrame(rows).to_csv(out / f"BRT_Pipeline_Timings_{ts}.csv", index=False)
            summary = {
                "run_id": self.run_id,
                "total_seconds": total_run,
                "phases": phases,
                "meta": self._meta,
            }
            (out / f"BRT_Pipeline_Timings_{ts}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            print(f"[PIPELINE] Wrote {out / f'BRT_Pipeline_Timings_{ts}.csv'}", flush=True)
        except Exception as e:
            print(f"[PIPELINE] Could not write timing CSV: {e}", file=sys.stderr)
        self._persist_duckdb(phases, total_run)

    def _persist_duckdb(self, phases: dict[str, float], total_run: float) -> None:
        db = self.db_path
        if db is None:
            return
        try:
            import duckdb
        except ImportError:
            print("[PIPELINE] DuckDB not installed; skipping timing DB persist.", file=sys.stderr)
            return
        try:
            db.parent.mkdir(parents=True, exist_ok=True)
            con = duckdb.connect(str(db))
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS brt_run_summary (
                    run_id VARCHAR PRIMARY KEY,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    total_seconds DOUBLE,
                    meta JSON
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS brt_run_phases (
                    run_id VARCHAR,
                    phase VARCHAR,
                    seconds DOUBLE,
                    pct_of_run DOUBLE,
                    PRIMARY KEY (run_id, phase)
                )
                """
            )
            started = datetime.fromtimestamp(self.started_at)
            finished = datetime.now()
            con.execute(
                "DELETE FROM brt_run_summary WHERE run_id = ?",
                [self.run_id],
            )
            con.execute(
                "INSERT INTO brt_run_summary (run_id, started_at, finished_at, total_seconds, meta) VALUES (?, ?, ?, ?, ?)",
                [self.run_id, started, finished, total_run, json.dumps(self._meta)],
            )
            con.execute("DELETE FROM brt_run_phases WHERE run_id = ?", [self.run_id])
            for phase, sec in phases.items():
                pct = 100.0 * sec / total_run if total_run > 0 else 0.0
                con.execute(
                    "INSERT INTO brt_run_phases (run_id, phase, seconds, pct_of_run) VALUES (?, ?, ?, ?)",
                    [self.run_id, phase, sec, pct],
                )
            con.close()
            print(f"[PIPELINE] Timings stored in DuckDB: {db}", flush=True)
        except Exception as e:
            print(f"[PIPELINE] DuckDB persist failed: {e}", file=sys.stderr)


def default_instrument_db_path(output_dir: Path) -> Path:
    return output_dir / "brt_profile.duckdb"
