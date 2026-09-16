"""
PHASE 6 — Ward-level social vulnerability from the OFFICIAL Census 2011 PCA
==========================================================================
Source: Census of India 2011, Primary Census Abstract (EB-level), district 342
        (Kolkata), file DDW_PCA1916_2011_MDDS with UI.xlsx
        recovered from the Wayback Machine (censusindia.gov.in is now defunct):
        https://web.archive.org/web/2020id_/http://censusindia.gov.in/pca/pcadata/DDW_PCA1916_2011_MDDS%20with%20UI.xlsx

Sheet "EB-1916" holds one row per KMC ward (Level == "WARD") with 94 columns:
households, population by sex, population below 6, SC/ST, literates/illiterates,
and the full worker classification (main/marginal x cultivator/agri-labour/
household-industry/other) plus non-workers.

WHAT THIS GIVES US (all real, all Census 2011):
    illiteracy_pct  - socioeconomic deprivation (the education signal used in
                      essentially every published heat-vulnerability index)
    hh_size         - persons per household, a crowding / housing-quality proxy
    worker_pct      - share of residents who work, i.e. outdoor exposure
    under6_pct      - child dependency
    scst_pct        - marginalised-caste share

WHAT IT DOES *NOT* GIVE US:
    Population aged 60+ — the single strongest driver of heat mortality. The PCA
    carries age only as "below 6 years". We deliberately do NOT invent it; see
    DATA.md. Non-worker share is reported for context but is NOT used as an
    elderly proxy because it is dominated by homemakers and students.

Run:  python -m scripts.build_demographics
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

XLSX = Path("data/raw/census2011_pca_1916.xlsx")
OUT = Path("data/census2011_ward_demographics.csv")
WARDS_CSV = Path("data/wards.csv")

# Official Census 2011 KMC total — the sum must match this exactly.
EXPECTED_TOTAL = 4_496_694
EXPECTED_WARDS = 141


def load_ward_rows(xlsx: Path = XLSX) -> pd.DataFrame:
    if not xlsx.exists():
        sys.exit(f"missing {xlsx} — rerun the Wayback download (see docstring)")
    raw = pd.read_excel(xlsx, sheet_name="EB-1916", dtype=str)
    raw.columns = [str(c).strip() for c in raw.columns]
    wards = raw[raw["Level"].astype(str).str.strip() == "WARD"].copy()
    if wards.empty:
        sys.exit("no rows with Level == 'WARD'")
    wards["ward_id"] = wards["Ward"].astype(str).str.strip().str.lstrip("0").astype(int)
    for c in wards.columns:
        if c in ("Level", "Name", "TRU", "Ward", "EB", "State", "District",
                 "Subdistt", "Town/Village", "ward_id"):
            continue
        wards[c] = pd.to_numeric(wards[c], errors="coerce")
    return wards.sort_values("ward_id").reset_index(drop=True)


def validate(w: pd.DataFrame) -> None:
    """Internal-consistency checks. These are the difference between real data
    and a plausible-looking spreadsheet."""
    checks = [
        ("ward count == 141", len(w) == EXPECTED_WARDS,
         f"{len(w)}"),
        ("population sums to 4,496,694", int(w["TOT_P"].sum()) == EXPECTED_TOTAL,
         f"{int(w['TOT_P'].sum()):,}"),
        ("male + female == total", bool((w["TOT_M"] + w["TOT_F"] == w["TOT_P"]).all()),
         "rowwise"),
        ("literate + illiterate == total", bool((w["P_LIT"] + w["P_ILL"] == w["TOT_P"]).all()),
         "rowwise"),
        ("workers + non-workers == total",
         bool((w["TOT_WORK_P"] + w["NON_WORK_P"] == w["TOT_P"]).all()), "rowwise"),
        ("no duplicate ward_id", w["ward_id"].is_unique, "unique"),
        ("ward ids 1..141", sorted(w["ward_id"]) == list(range(1, 142)), "complete"),
        ("no nulls in key columns",
         bool(w[["TOT_P", "P_ILL", "No_HH", "P_06", "TOT_WORK_P"]].notna().all().all()), "ok"),
    ]
    print("Validation")
    print("-" * 62)
    ok = True
    for label, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label:36s} {detail}")
        ok &= bool(passed)
    if not ok:
        sys.exit("census demographics failed validation — refusing to write")
    print()


def build(w: pd.DataFrame) -> pd.DataFrame:
    p = w["TOT_P"]
    return pd.DataFrame({
        "ward_id": w["ward_id"],
        "households": w["No_HH"].astype(int),
        "pop_male": w["TOT_M"].astype(int),
        "pop_female": w["TOT_F"].astype(int),
        "pop_under6": w["P_06"].astype(int),
        "pop_sc": w["P_SC"].astype(int),
        "pop_st": w["P_ST"].astype(int),
        "pop_literate": w["P_LIT"].astype(int),
        "pop_illiterate": w["P_ILL"].astype(int),
        "workers_total": w["TOT_WORK_P"].astype(int),
        "workers_main": w["MAINWORK_P"].astype(int),
        "workers_marginal": w["MARGWORK_P"].astype(int),
        "workers_other": w["MAIN_OT_P"].astype(int),   # urban non-farm labour
        "non_workers": w["NON_WORK_P"].astype(int),
        # --- derived rates (the things that actually enter the model) ---
        "illiteracy_pct": (w["P_ILL"] / p * 100).round(2),
        "hh_size": (p / w["No_HH"]).round(2),
        "worker_pct": (w["TOT_WORK_P"] / p * 100).round(2),
        "under6_pct": (w["P_06"] / p * 100).round(2),
        "scst_pct": ((w["P_SC"] + w["P_ST"]) / p * 100).round(2),
        "nonworker_pct": (w["NON_WORK_P"] / p * 100).round(2),
    })


def merge_into_wards(demo: pd.DataFrame, wards_csv: Path = WARDS_CSV) -> None:
    """Attach the demographic columns to data/wards.csv, keeping a backup."""
    if not wards_csv.exists():
        print("no data/wards.csv — skipping merge")
        return
    wards = pd.read_csv(wards_csv)
    before = list(wards.columns)
    backup = wards_csv.with_suffix(".pre-demographics.csv")
    if not backup.exists():
        wards.to_csv(backup, index=False)
    cols = [c for c in demo.columns if c != "ward_id"]
    wards = wards.drop(columns=[c for c in cols if c in wards.columns])
    merged = wards.merge(demo, on="ward_id", how="left")
    missing = merged["illiteracy_pct"].isna().sum()
    merged.to_csv(wards_csv, index=False)
    print(f"Merged {len(cols)} demographic columns into {wards_csv}")
    print(f"  backup          -> {backup}")
    print(f"  columns before  -> {len(before)}, after -> {len(merged.columns)}")
    print(f"  wards missing demographics: {missing}")


def main() -> None:
    pd.set_option("display.width", 200)
    w = load_ward_rows()
    validate(w)
    demo = build(w)
    demo.to_csv(OUT, index=False)
    print(f"Wrote {OUT}  ({len(demo)} wards x {demo.shape[1]} cols)\n")

    print("Derived social indicators across the 141 wards")
    print("-" * 62)
    print(demo[["illiteracy_pct", "hh_size", "worker_pct",
                "under6_pct", "scst_pct"]].describe().round(2).to_string())

    print("\nMost deprived wards (highest illiteracy)")
    print("-" * 62)
    print(demo.nlargest(5, "illiteracy_pct")[
        ["ward_id", "illiteracy_pct", "hh_size", "worker_pct"]].to_string(index=False))
    print("\nLeast deprived wards (lowest illiteracy)")
    print("-" * 62)
    print(demo.nsmallest(5, "illiteracy_pct")[
        ["ward_id", "illiteracy_pct", "hh_size", "worker_pct"]].to_string(index=False))

    merge_into_wards(demo)


if __name__ == "__main__":
    main()
