#!/usr/bin/env python3
"""Validate mobile_trades.csv and merge into house Actual / getTarget / closed ledgers.

Phone CSV columns (drive/mobile_inbox/mobile_trades.csv):
  date, symbol, side (BUY/SELL), qty, price, system, account, notes

Writes / updates:
  - drive/mobile_inbox/fidelity_mobile_supplement.csv  (Fidelity Accounts_History shape)
  - gettarget_positions.csv                           (BUY upsert / SELL remove)
  - trade_system_registry.csv                         (BUY append if missing)
  - closed_positions_log.csv                          (SELL round-trips when buy known)
Archives processed rows to drive/mobile_inbox/archive/ and clears pending file header.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")

INBOX = ROOT / "drive" / "mobile_inbox"
DEFAULT_MOBILE = INBOX / "mobile_trades.csv"
DEFAULT_SUPPLEMENT = INBOX / "fidelity_mobile_supplement.csv"
DEFAULT_POSITIONS = ROOT / "gettarget_positions.csv"
DEFAULT_REGISTRY = ROOT / "trade_system_registry.csv"
DEFAULT_CLOSED_LOG = ROOT / "closed_positions_log.csv"
ARCHIVE_DIR = INBOX / "archive"

MOBILE_COLUMNS = ("date", "symbol", "side", "qty", "price", "system", "account", "notes")
FIDELITY_COLUMNS = (
    "Run Date",
    "Action",
    "Symbol",
    "Description",
    "Currency",
    "Price",
    "Quantity",
    "Amount",
    "Settlement Date",
)
CLOSED_LOG_COLUMNS = (
    "symbol",
    "system",
    "buy_date",
    "buy_price",
    "sell_date",
    "sell_price",
    "qty",
    "pnl_pct",
    "pnl_dollars",
    "original_qty",
    "purchase_value",
    "recorded_at",
)
POSITIONS_COLUMNS = ("symbol", "purchase_date", "entry_price", "system")
ALLOWED_SYSTEMS = frozenset(
    {"BRT", "IND", "RL", "YH", "MTS", "WPBR", "PBR", "RS", "SB", "VZ", "MVCP", "CS"}
)
_SYSTEM_ALIASES = {
    "PBR": "WPBR",
    "STOCKBEE": "SB",
    "MINERVINI": "MVCP",
    "VCP": "MVCP",
    "CANSLIM": "CS",
    "CAN_SLIM": "CS",
}


def _normalize_system(raw: str) -> str:
    s = str(raw or "").strip().upper().replace(" ", "_")
    return _SYSTEM_ALIASES.get(s, s)


def _parse_date(raw: object) -> Optional[date]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s:
        return None
    ts = pd.to_datetime(s, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _fidelity_row(trade: dict) -> dict:
    side = trade["side"]
    sym = trade["symbol"]
    qty = float(trade["qty"])
    price = float(trade["price"])
    d = trade["date"]
    acct = trade.get("account") or "Margin"
    d_str = d.isoformat() if isinstance(d, date) else str(d)
    if side == "BUY":
        action = f"YOU BOUGHT {sym} (mobile) ({acct})"
        amount = -abs(qty * price)
    else:
        action = f"YOU SOLD {sym} (mobile) ({acct})"
        amount = abs(qty * price)
    return {
        "Run Date": d_str,
        "Action": action,
        "Symbol": sym,
        "Description": trade.get("notes") or f"mobile {side}",
        "Currency": "USD",
        "Price": round(price, 6),
        "Quantity": abs(qty),
        "Amount": round(amount, 2),
        "Settlement Date": d_str,
    }


def _load_mobile(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame(columns=list(MOBILE_COLUMNS))
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if df.empty:
        return pd.DataFrame(columns=list(MOBILE_COLUMNS))
    cols = {c.lower().strip(): c for c in df.columns}
    rename = {}
    for need in MOBILE_COLUMNS:
        if need in cols:
            rename[cols[need]] = need
        elif need == "date" and "run date" in cols:
            rename[cols["run date"]] = "date"
        elif need == "side" and "action" in cols:
            rename[cols["action"]] = "side"
    df = df.rename(columns=rename)
    for c in MOBILE_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[list(MOBILE_COLUMNS)].copy()


def _validate_rows(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    ok: list[dict] = []
    errors: list[str] = []
    for i, r in df.iterrows():
        row_n = int(i) + 2  # header = 1
        # Skip blank / template rows
        sym_raw = str(r.get("symbol", "")).strip().upper()
        if not sym_raw or sym_raw == "EXAMPLE":
            continue
        side_raw = str(r.get("side", "")).strip().upper()
        if side_raw in ("YOU BOUGHT", "BOUGHT", "B"):
            side = "BUY"
        elif side_raw in ("YOU SOLD", "SOLD", "S"):
            side = "SELL"
        else:
            side = side_raw
        if side not in ("BUY", "SELL"):
            errors.append(f"row {row_n}: side must be BUY or SELL (got {side_raw!r})")
            continue
        d = _parse_date(r.get("date"))
        if d is None:
            errors.append(f"row {row_n}: bad date {r.get('date')!r}")
            continue
        try:
            qty = abs(float(str(r.get("qty", "")).replace(",", "").strip()))
            price = abs(float(str(r.get("price", "")).replace(",", "").strip()))
        except (TypeError, ValueError):
            errors.append(f"row {row_n}: qty/price must be numeric")
            continue
        if qty <= 0 or price <= 0:
            errors.append(f"row {row_n}: qty and price must be > 0")
            continue
        system = _normalize_system(str(r.get("system", "")))
        if system and system not in ALLOWED_SYSTEMS:
            errors.append(f"row {row_n}: unknown system {system!r}")
            continue
        if side == "BUY" and not system:
            errors.append(f"row {row_n}: BUY requires system (RS/SB/VZ/…)")
            continue
        ok.append(
            {
                "date": d,
                "symbol": sym_raw,
                "side": side,
                "qty": qty,
                "price": price,
                "system": system,
                "account": str(r.get("account", "")).strip() or "Margin",
                "notes": str(r.get("notes", "")).strip(),
            }
        )
    return ok, errors


def _fingerprint(row: dict) -> tuple:
    return (
        str(row["Run Date"]),
        str(row["Symbol"]).upper(),
        "BUY" if "YOU BOUGHT" in str(row["Action"]) else "SELL",
        round(float(row["Quantity"]), 4),
        round(float(row["Price"]), 6),
    )


def _merge_supplement(path: Path, new_rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.DataFrame(columns=list(FIDELITY_COLUMNS))
    if path.is_file() and path.stat().st_size > 0:
        existing = pd.read_csv(path, dtype=str, keep_default_na=False)
        for c in FIDELITY_COLUMNS:
            if c not in existing.columns:
                existing[c] = ""
        existing = existing[list(FIDELITY_COLUMNS)]
    seen = {_fingerprint(r) for _, r in existing.iterrows()}
    added = 0
    frames = [existing] if not existing.empty else []
    extra: list[dict] = []
    for row in new_rows:
        fp = _fingerprint(row)
        if fp in seen:
            continue
        seen.add(fp)
        extra.append(row)
        added += 1
    if extra:
        frames.append(pd.DataFrame(extra, columns=list(FIDELITY_COLUMNS)))
        out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(extra)
        out.to_csv(path, index=False)
    elif not path.is_file():
        pd.DataFrame(columns=list(FIDELITY_COLUMNS)).to_csv(path, index=False)
    return added


def _load_positions(path: Path) -> pd.DataFrame:
    if path.is_file() and path.stat().st_size > 0:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        cols = {c.lower(): c for c in df.columns}
        rename = {}
        for want, alts in (
            ("symbol", ("symbol",)),
            ("purchase_date", ("purchase_date", "purchasedate")),
            ("entry_price", ("entry_price", "entryprice")),
            ("system", ("system",)),
        ):
            for a in alts:
                if a in cols:
                    rename[cols[a]] = want
                    break
        df = df.rename(columns=rename)
        for c in POSITIONS_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        return df[list(POSITIONS_COLUMNS)].copy()
    return pd.DataFrame(columns=list(POSITIONS_COLUMNS))


def _save_positions(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[list(POSITIONS_COLUMNS)].copy()
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out["system"] = out["system"].map(_normalize_system)
    out = out[out["symbol"].astype(str).str.len() > 0]
    out = out.sort_values(["symbol", "purchase_date"]).reset_index(drop=True)
    out.to_csv(path, index=False)


def _upsert_position(df: pd.DataFrame, trade: dict) -> pd.DataFrame:
    sym = trade["symbol"]
    pd_s = trade["date"].isoformat()
    mask = (df["symbol"].str.upper() == sym) & (
        df["purchase_date"].astype(str).str[:10] == pd_s
    )
    row = {
        "symbol": sym,
        "purchase_date": pd_s,
        "entry_price": str(round(float(trade["price"]), 6)),
        "system": trade["system"],
    }
    if mask.any():
        df.loc[mask, list(row.keys())] = list(row.values())
        return df
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)


def _remove_position(df: pd.DataFrame, trade: dict) -> pd.DataFrame:
    """Remove open book row for symbol (prefer matching purchase_date via notes buy_date=)."""
    sym = trade["symbol"]
    notes = trade.get("notes") or ""
    buy_date = None
    for part in notes.replace(";", ",").split(","):
        part = part.strip()
        if part.lower().startswith("buy_date="):
            buy_date = _parse_date(part.split("=", 1)[1])
            break
    mask = df["symbol"].str.upper() == sym
    if buy_date is not None:
        mask = mask & (df["purchase_date"].astype(str).str[:10] == buy_date.isoformat())
    if not mask.any():
        return df
    # If multiple open lots and no buy_date, remove oldest matching symbol.
    idxs = df.index[mask].tolist()
    if buy_date is None and len(idxs) > 1:
        idxs = [sorted(idxs, key=lambda i: str(df.loc[i, "purchase_date"]))[0]]
    return df.drop(index=idxs).reset_index(drop=True)


def _append_registry(path: Path, trade: dict) -> bool:
    if trade["side"] != "BUY" or not trade.get("system"):
        return False
    sym = trade["symbol"]
    pd_s = trade["date"].isoformat()
    system = trade["system"]
    if path.is_file() and path.stat().st_size > 0:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        cols = {c.lower(): c for c in df.columns}
        sym_c = cols.get("symbol", "symbol")
        date_c = cols.get("purchase_date", cols.get("purchasedate", "purchase_date"))
        sys_c = cols.get("system", "system")
        for _, r in df.iterrows():
            if (
                str(r.get(sym_c, "")).strip().upper() == sym
                and str(r.get(date_c, "")).strip()[:10] == pd_s
            ):
                return False
        write_header = False
    else:
        write_header = True
        path.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame(
        [{"symbol": sym, "purchase_date": pd_s, "system": system}]
    )
    row.to_csv(path, mode="a", header=write_header, index=False)
    return True


def _closed_key(row: dict) -> tuple:
    return (
        str(row["symbol"]).upper(),
        str(row["buy_date"])[:10],
        str(row["sell_date"])[:10],
        round(float(row["qty"]), 4),
        round(float(row["sell_price"]), 6),
        round(float(row["buy_price"]), 6),
    )


def _append_closed_from_sell(
    log_path: Path, positions: pd.DataFrame, trade: dict
) -> bool:
    """Best-effort closed log row using matching open position for buy side."""
    sym = trade["symbol"]
    mask = positions["symbol"].str.upper() == sym
    if not mask.any():
        return False
    # Prefer notes buy_date=; else oldest open lot.
    notes = trade.get("notes") or ""
    buy_date = None
    for part in notes.replace(";", ",").split(","):
        part = part.strip()
        if part.lower().startswith("buy_date="):
            buy_date = _parse_date(part.split("=", 1)[1])
            break
    cand = positions.loc[mask].copy()
    if buy_date is not None:
        cand = cand[cand["purchase_date"].astype(str).str[:10] == buy_date.isoformat()]
    if cand.empty:
        return False
    cand = cand.sort_values("purchase_date")
    pos = cand.iloc[0]
    try:
        buy_price = float(pos.get("entry_price") or 0)
    except (TypeError, ValueError):
        buy_price = 0.0
    if buy_price <= 0:
        buy_price = float(trade["price"])
    buy_d = str(pos.get("purchase_date", ""))[:10]
    sell_d = trade["date"].isoformat()
    qty = float(trade["qty"])
    sell_price = float(trade["price"])
    pnl_pct = (sell_price - buy_price) / buy_price * 100.0 if buy_price else 0.0
    pnl_dollars = qty * (sell_price - buy_price)
    recorded_at = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S %Z")
    row = {
        "symbol": sym,
        "system": _normalize_system(str(pos.get("system") or trade.get("system") or "")),
        "buy_date": buy_d,
        "buy_price": round(buy_price, 6),
        "sell_date": sell_d,
        "sell_price": round(sell_price, 6),
        "qty": round(qty, 4),
        "pnl_pct": round(pnl_pct, 6),
        "pnl_dollars": round(pnl_dollars, 2),
        "original_qty": round(qty, 4),
        "purchase_value": round(qty * buy_price, 2),
        "recorded_at": recorded_at,
    }
    existing_keys: set[tuple] = set()
    if log_path.is_file() and log_path.stat().st_size > 0:
        old = pd.read_csv(log_path, dtype=str, keep_default_na=False)
        for _, r in old.iterrows():
            try:
                existing_keys.add(
                    _closed_key(
                        {
                            "symbol": r.get("symbol", ""),
                            "buy_date": r.get("buy_date", ""),
                            "sell_date": r.get("sell_date", ""),
                            "qty": r.get("qty", 0),
                            "sell_price": r.get("sell_price", 0),
                            "buy_price": r.get("buy_price", 0),
                        }
                    )
                )
            except (TypeError, ValueError):
                continue
        write_header = False
    else:
        write_header = True
        log_path.parent.mkdir(parents=True, exist_ok=True)
    if _closed_key(row) in existing_keys:
        return False
    pd.DataFrame([row], columns=list(CLOSED_LOG_COLUMNS)).to_csv(
        log_path, mode="a", header=write_header, index=False
    )
    return True


def ingest(
    mobile_path: Path,
    supplement_path: Path,
    positions_path: Path,
    registry_path: Path,
    closed_log_path: Path,
    *,
    dry_run: bool = False,
) -> dict:
    raw = _load_mobile(mobile_path)
    trades, errors = _validate_rows(raw)
    if errors:
        raise SystemExit("Validation failed:\n  - " + "\n  - ".join(errors))
    if not trades:
        return {
            "trades": 0,
            "supplement_added": 0,
            "positions_updated": 0,
            "registry_added": 0,
            "closed_added": 0,
            "message": "No pending mobile trades",
        }

    fidelity_rows = [_fidelity_row(t) for t in trades]
    positions = _load_positions(positions_path)
    # Snapshot for closed-log matching before removals.
    positions_before = positions.copy()

    pos_updates = 0
    reg_adds = 0
    closed_adds = 0
    for t in trades:
        if t["side"] == "BUY":
            positions = _upsert_position(positions, t)
            pos_updates += 1
            if not dry_run and _append_registry(registry_path, t):
                reg_adds += 1
        else:
            if not dry_run and _append_closed_from_sell(
                closed_log_path, positions_before, t
            ):
                closed_adds += 1
            positions = _remove_position(positions, t)
            pos_updates += 1

    if dry_run:
        return {
            "trades": len(trades),
            "supplement_added": len(fidelity_rows),
            "positions_updated": pos_updates,
            "registry_added": reg_adds,
            "closed_added": closed_adds,
            "message": "dry-run only",
        }

    supp_added = _merge_supplement(supplement_path, fidelity_rows)
    _save_positions(positions_path, positions)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
    archive_path = ARCHIVE_DIR / f"mobile_trades_done_{stamp}.csv"
    pd.DataFrame(trades).to_csv(archive_path, index=False)
    # Clear pending (keep header)
    pd.DataFrame(columns=list(MOBILE_COLUMNS)).to_csv(mobile_path, index=False)
    # Keep a small marker of last ingest
    (INBOX / "last_ingest.txt").write_text(
        f"{stamp} trades={len(trades)} supplement+={supp_added} "
        f"positions~={pos_updates} registry+={reg_adds} closed+={closed_adds}\n",
        encoding="utf-8",
    )
    return {
        "trades": len(trades),
        "supplement_added": supp_added,
        "positions_updated": pos_updates,
        "registry_added": reg_adds,
        "closed_added": closed_adds,
        "archive": str(archive_path),
        "message": "ok",
    }


def apply_gettarget_patch(
    patch_path: Path,
    positions_path: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Merge gettarget_positions_PATCH.csv → gettarget_positions.csv (ADD/UPSERT/REMOVE)."""
    if not patch_path.is_file():
        return {"applied": 0, "message": f"No patch file: {patch_path}"}
    df = pd.read_csv(patch_path, dtype=str, keep_default_na=False)
    if df.empty:
        return {"applied": 0, "message": "Empty patch"}
    cols = {c.lower().strip(): c for c in df.columns}
    for need in ("op", "symbol"):
        if need not in cols:
            raise SystemExit(f"Patch missing column {need}")
    positions = _load_positions(positions_path)
    applied = 0
    errors: list[str] = []
    for i, r in df.iterrows():
        row_n = int(i) + 2
        op = str(r[cols["op"]]).strip().upper()
        sym = str(r[cols["symbol"]]).strip().upper()
        if not sym or sym == "EXAMPLE" or not op:
            continue
        date_c = cols.get("purchase_date", cols.get("purchasedate"))
        price_c = cols.get("entry_price", cols.get("entryprice"))
        sys_c = cols.get("system")
        pd_s = str(r[date_c]).strip()[:10] if date_c else ""
        system = _normalize_system(str(r[sys_c]).strip() if sys_c else "")
        price = str(r[price_c]).strip() if price_c else ""
        if op in ("ADD", "UPSERT"):
            if not pd_s or not system:
                errors.append(f"row {row_n}: {op} needs purchase_date and system")
                continue
            if system not in ALLOWED_SYSTEMS:
                errors.append(f"row {row_n}: bad system {system}")
                continue
            trade = {
                "symbol": sym,
                "date": _parse_date(pd_s) or date.fromisoformat(pd_s),
                "price": float(price) if price else 0.0,
                "system": system,
            }
            positions = _upsert_position(positions, trade)
            applied += 1
        elif op == "REMOVE":
            mask = positions["symbol"].str.upper() == sym
            if pd_s:
                mask = mask & (positions["purchase_date"].astype(str).str[:10] == pd_s)
            if mask.any():
                positions = positions.loc[~mask].reset_index(drop=True)
                applied += 1
        else:
            errors.append(f"row {row_n}: op must be ADD, UPSERT, or REMOVE (got {op!r})")
    if errors:
        raise SystemExit("Patch validation failed:\n  - " + "\n  - ".join(errors))
    if dry_run:
        return {"applied": applied, "message": "dry-run only"}
    _save_positions(positions_path, positions)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ET).strftime("%Y%m%d_%H%M%S")
    dest = ARCHIVE_DIR / f"gettarget_positions_PATCH_done_{stamp}.csv"
    shutil.copy2(patch_path, dest)
    # Reset patch to header + instruction row commented via empty
    pd.DataFrame(
        columns=["op", "symbol", "purchase_date", "entry_price", "system", "notes"]
    ).to_csv(patch_path, index=False)
    return {"applied": applied, "archive": str(dest), "message": "ok"}


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Ingest drive/mobile_inbox mobile trades / getTarget patch")
    p.add_argument("--mobile", type=Path, default=DEFAULT_MOBILE)
    p.add_argument("--supplement", type=Path, default=DEFAULT_SUPPLEMENT)
    p.add_argument("--positions", type=Path, default=DEFAULT_POSITIONS)
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    p.add_argument("--closed-log", type=Path, default=DEFAULT_CLOSED_LOG)
    p.add_argument(
        "--patch",
        type=Path,
        default=INBOX / "gettarget_positions_PATCH.csv",
        help="gettarget_positions_PATCH.csv path",
    )
    p.add_argument(
        "--apply-patch-only",
        action="store_true",
        help="Only apply gettarget_positions_PATCH.csv",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.apply_patch_only:
        result = apply_gettarget_patch(args.patch, args.positions, dry_run=args.dry_run)
    else:
        result = ingest(
            args.mobile,
            args.supplement,
            args.positions,
            args.registry,
            args.closed_log,
            dry_run=args.dry_run,
        )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
