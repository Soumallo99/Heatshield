"""
PHASE 5b — Ward-level subscriber registry.

Phase 5 could only address one hard-coded number from .env. That is fine for a
demo and useless in practice: a heat warning for Ward 24 should reach the people
in Ward 24 plus the duty officer, not everybody on one list.

This module keeps a tiny CSV registry:

    phone,name,ward_id,role,opted_out,created_at,notes

  ward_id   a real ward (1-141), or 0 for CITYWIDE recipients (duty officer,
            health department) who receive every ward's alert.
  role      resident | official | health_worker — decides the message variant later.
  opted_out STOP handling is a legal requirement, not a nicety: replying STOP
            must suppress every further message from that number.

Why CSV and not a database: 141 wards and a few thousand rows is nothing, the
file is diffable and auditable, and it ships with the repo so the prototype runs
with zero setup. Swap the two IO functions for a real datastore when the
recipient count justifies it.

DEMO DATA — the seeded rows are PLACEHOLDER numbers, not real people.
Replace data/subscribers.csv before any live send.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.config import DATA_DIR
from core.security import sanitise_cell

REGISTRY_CSV = DATA_DIR / "subscribers.csv"

COLS = ["phone", "name", "ward_id", "role", "opted_out", "created_at", "notes"]

ROLES = ("resident", "official", "health_worker")
CITYWIDE = 0  # ward_id meaning "send me everything"
WARD_MAX = 141                   # KMC ward count (see DATA.md)
NAME_MAX = 80                    # a display name, not an essay
NOTES_MAX = 300


# --------------------------------------------------------------------------- #
# normalisation
# --------------------------------------------------------------------------- #

def normalise_phone(raw: str) -> str:
    """
    '+91 98765 43210', '09876543210', '9876543210' -> '+919876543210'

    Twilio rejects anything that isn't E.164, and a registry that stores five
    spellings of the same number will alert the same person five times.
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return ""
    if len(digits) == 10:                      # bare Indian mobile
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return "+" + digits


# --------------------------------------------------------------------------- #
# IO
# --------------------------------------------------------------------------- #

def load_registry(path: Path | str = REGISTRY_CSV) -> pd.DataFrame:
    """Always returns a well-formed frame, even if the file is missing/empty."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=COLS)
    try:
        df = pd.read_csv(path, dtype={"phone": str})
    except Exception:                                   # noqa: BLE001
        return pd.DataFrame(columns=COLS)
    for c in COLS:
        if c not in df.columns:
            df[c] = "" if c != "ward_id" else 0
    df = df[COLS].copy()
    df["ward_id"] = pd.to_numeric(df["ward_id"], errors="coerce").fillna(0).astype(int)
    df["opted_out"] = df["opted_out"].astype(str).str.strip().str.lower().isin(
        {"1", "true", "yes", "y"}
    )
    df["phone"] = df["phone"].map(normalise_phone)
    # Empty CSV cells arrive as float NaN. `json.dumps` refuses NaN, so one blank
    # `name` or `notes` field used to turn the whole registry route into a 500.
    for column in ("name", "role", "notes", "created_at"):
        df[column] = df[column].astype(object).where(pd.notna(df[column]), "")
    return df


def save_registry(df: pd.DataFrame, path: Path | str = REGISTRY_CSV) -> pd.DataFrame:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[COLS].copy()
    out.to_csv(path, index=False)
    return df


# --------------------------------------------------------------------------- #
# mutations
# --------------------------------------------------------------------------- #

def add_subscriber(
    phone: str,
    ward_id: int = CITYWIDE,
    name: str = "",
    role: str = "resident",
    notes: str = "",
    path: Path | str = REGISTRY_CSV,
) -> dict:
    """
    Add or re-subscribe a number. Re-adding an opted-out number opts it back in —
    that is the only safe reading of someone deliberately texting in again.
    """
    p = normalise_phone(phone)
    if not p:
        return {"ok": False, "error": "invalid phone number"}
    if not re.fullmatch(r"\+\d{8,15}", p):
        return {"ok": False, "error": "phone must be a full international number"}
    if role not in ROLES:
        return {"ok": False, "error": f"role must be one of {ROLES}"}
    ward_id = int(ward_id)
    if not (CITYWIDE <= ward_id <= WARD_MAX):
        return {"ok": False, "error": f"ward_id must be {CITYWIDE} (citywide) or 1-{WARD_MAX}"}
    # Registry text is neutralised before it is written: a name starting with "="
    # is a spreadsheet formula, not a person (CWE-1236), and unbounded strings
    # let one request fill the disk.
    name = sanitise_cell(name, max_length=NAME_MAX)
    notes = sanitise_cell(notes, max_length=NOTES_MAX)

    df = load_registry(path)
    mask = df["phone"] == p
    now = datetime.now().isoformat(timespec="seconds")

    if mask.any():
        df.loc[mask, ["ward_id", "name", "role", "opted_out", "notes"]] = [
            int(ward_id), name, role, False, notes
        ]
        action = "updated"
    else:
        df = pd.concat(
            [df, pd.DataFrame([{
                "phone": p, "name": name, "ward_id": int(ward_id), "role": role,
                "opted_out": False, "created_at": now, "notes": notes,
            }])],
            ignore_index=True,
        )
        action = "added"

    save_registry(df, path)
    return {"ok": True, "action": action, "phone": p, "ward_id": int(ward_id), "role": role}


def opt_out(phone: str, path: Path | str = REGISTRY_CSV) -> dict:
    """STOP. Idempotent, and never fails loudly — silence is the requested outcome."""
    p = normalise_phone(phone)
    if not p or not re.fullmatch(r"\+\d{8,15}", p):
        return {"ok": False, "error": "invalid phone number"}
    df = load_registry(path)
    mask = df["phone"] == p
    if not mask.any():
        # Add them as opted-out so a later re-subscribe is a deliberate act.
        df = pd.concat(
            [df, pd.DataFrame([{
                "phone": p, "name": "", "ward_id": CITYWIDE, "role": "resident",
                "opted_out": True, "created_at": datetime.now().isoformat(timespec="seconds"),
                "notes": "opted out before subscribing",
            }])],
            ignore_index=True,
        )
        save_registry(df, path)
        return {"ok": True, "action": "recorded", "phone": p, "opted_out": True}

    df.loc[mask, "opted_out"] = True
    save_registry(df, path)
    return {"ok": True, "action": "opted_out", "phone": p, "opted_out": True}


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #

def recipients_for_ward(ward_id: int, path: Path | str = REGISTRY_CSV) -> list[str]:
    """Numbers that should receive an alert for this ward: locals + citywide."""
    df = load_registry(path)
    if df.empty:
        return []
    live = df[~df["opted_out"]]
    sel = live[(live["ward_id"] == int(ward_id)) | (live["ward_id"] == CITYWIDE)]
    # de-duplicate while preserving order
    seen, out = set(), []
    for n in sel["phone"]:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def registry_stats(path: Path | str = REGISTRY_CSV) -> dict:
    df = load_registry(path)
    if df.empty:
        return {"total": 0, "active": 0, "opted_out": 0, "wards_covered": 0, "citywide": 0}
    live = df[~df["opted_out"]]
    return {
        "total": int(len(df)),
        "active": int(len(live)),
        "opted_out": int(len(df) - len(live)),
        "wards_covered": int(live[live["ward_id"] != CITYWIDE]["ward_id"].nunique()),
        "citywide": int((live["ward_id"] == CITYWIDE).sum()),
        "by_role": live["role"].value_counts().to_dict() if len(live) else {},
    }


def seed_demo_registry(path: Path | str = REGISTRY_CSV, force: bool = False) -> dict:
    """
    Write PLACEHOLDER rows so the prototype has something to resolve against.

    These are deliberately fake numbers (+91 00000 0xxxx) — they can never send
    a real message, which is exactly the point for a dry-run prototype.
    """
    path = Path(path)
    if path.exists() and not force:
        return {"ok": False, "error": "registry already exists (use force=True to overwrite)"}

    now = datetime.now().isoformat(timespec="seconds")
    rows = []

    # citywide duty officers — E.164 from the start ("+91" + 10 digits), so
    # normalise_phone() is a no-op rather than re-prefixing a short number.
    for i, (name, role) in enumerate([
        ("KMC Duty Officer", "official"),
        ("Health Dept Control Room", "health_worker"),
    ]):
        rows.append({
            "phone": f"+91{9900000000 + i}", "name": name, "ward_id": CITYWIDE,
            "role": role, "opted_out": False, "created_at": now,
            "notes": "DEMO PLACEHOLDER — replace with a real number before live send",
        })

    # two residents for each of the wards the model currently flags, plus a few more
    wards = [24, 23, 39, 18, 42, 48, 49, 29, 66, 1]
    n = 100
    for w in wards:
        for k in range(2):
            rows.append({
                "phone": f"+91{n:010d}", "name": f"Demo resident {w}-{k + 1}",
                "ward_id": w, "role": "resident", "opted_out": False,
                "created_at": now,
                "notes": "DEMO PLACEHOLDER — replace with a real number before live send",
            })
            n += 1

    # one opted-out row so the STOP path is visible in the UI
    rows.append({
        "phone": f"+91{n:010d}", "name": "Demo resident (STOPPED)", "ward_id": 24,
        "role": "resident", "opted_out": True, "created_at": now,
        "notes": "DEMO — replied STOP; must never be messaged",
    })

    df = pd.DataFrame(rows, columns=COLS)
    save_registry(df, path)
    return {"ok": True, "rows": len(df), "path": str(path)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="HeatShield subscriber registry")
    ap.add_argument("--seed", action="store_true", help="write DEMO placeholder rows")
    ap.add_argument("--stats", action="store_true", help="print registry statistics")
    ap.add_argument("--add", metavar="PHONE")
    ap.add_argument("--ward", type=int, default=CITYWIDE)
    ap.add_argument("--name", default="")
    ap.add_argument("--role", default="resident", choices=list(ROLES))
    ap.add_argument("--stop", metavar="PHONE", help="opt a number out (STOP)")
    ap.add_argument("--for-ward", type=int, metavar="WARD", help="who receives an alert for WARD")
    args = ap.parse_args()

    if args.seed:
        print(seed_demo_registry(force=True))
    if args.add:
        print(add_subscriber(args.add, args.ward, args.name, args.role))
    if args.stop:
        print(opt_out(args.stop))
    if args.for_ward:
        print(recipients_for_ward(args.for_ward))
    if args.stats or not any(
        [args.seed, args.add, args.stop, args.for_ward is not None]
    ):
        print(registry_stats())
