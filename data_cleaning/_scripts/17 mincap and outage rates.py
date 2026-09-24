"""
Script 17: MinCap and Outage Rates

Enriches colorado_resources.csv (Script 16 output) with:
  - MinCap (MW) and mincap_source
  - FOR (%), FORLength (days), MOR (%)

New columns: MinCap, mincap_source, FOR, FORLength, MOR, gads_bin

────────────────────────────────────────────────────────────────────────────
MinCap  (EIA Form 860, 2024)
────────────────────────────────────────────────────────────────────────────
Source: EIA Form 860, 3_1_Generator_Y2024.xlsx, 'Minimum Load (MW)' field.
File: data_cleaning/resources/eia860/raw/eia860_2024.zip

Matching strategy:
- For each resource, all (plant_code, generator_id) pairs are looked up in
  EIA-860.
- Capacity-weighted average Pmin fraction is computed across matched units:
    pmin_frac = sum(min_load_mw) / sum(nameplate_mw)
- MinCap (resource-level) = pmin_frac × MaxCap
- Proposed resources with no EIA-860 match receive the capacity-weighted
  average Pmin fraction of existing Colorado resources of the same TechType.

MinCap is resource-total, matching MaxCap/MaxStorage/PaybckCap/max_discharge_mw
(all already resource-level aggregates, e.g. MaxCap = summer_mw.sum() across a
group's units -- Script 14) -- NOT per-unit. Originally stored per-unit
(pmin_frac x (MaxCap/Units)); changed 2026-08-14 after building a PyPSA
translation surfaced the inconsistency (every other capacity-like column is
already resource-total, so a per-unit MinCap silently needed multiplying by
Units to mean the same thing, and nothing about the column name signaled
that). Likely also corrects a latent understatement of the min-generation
constraint in the already-imported EnCompass resource sheet, which receives
this column directly (encompass/scripts/4's RESOURCE_SHEET_DIRECT_COLS) and
was getting the per-unit value paired against an already-resource-total
MaxCap.

Special cases:
- Wind / Solar:PV / Solar:CSP → MinCap = MaxCap (must-run via MinOnline;
  actual output bounded by hourly NetGenLim profile)
- Storage:Battery → MinCap = 0 (governed by MaxStorage / PaybckReq)

────────────────────────────────────────────────────────────────────────────
Outage Rates  (NERC GADS, 2020–2024)
────────────────────────────────────────────────────────────────────────────
Source: NERC Generating Unit Statistical Brochure, 2020–2024 (All Units
Reporting).
File: data_cleaning/resources/nercgads/
      generating-unit-statistical-brochure-4-2020---2024---all-units-reporting.xlsx
Sheet: 2024-04

Column mapping (row 0 headers in that file):
  col  0  Generator Category
  col  4  Unit-Years
  col 15  FOH   — Forced Outage Hours per unit-year
  col 16  #FOH  — Forced Outage Events per unit-year
  col 32  MOF   — Maintenance Outage Factor (%)
  col 42  EFORd — Equivalent Demand Forced Outage Rate (%)

Parameter derivation:
  FOR       = EFORd   (not raw GADS FOR, which inflates peaker rates by
              counting reserve-shutdown hours; EFORd conditions on hours
              the unit was actually demanded)
  FORLength = FOH / #FOH / 24  [days]  (avg duration of one FO event)
  MOR       = MOF

Size-bin matching:
  Each resource is matched to the tightest GADS size bin whose MW range
  contains the resource's per-unit capacity (MaxCap / Units). Where the
  brochure only publishes an "All Sizes" aggregate (Gas:CC, Hydro:Pumped)
  that row is used directly. Resources whose per-unit MW falls below the
  bottom of the smallest bin also fall back to "All Sizes".

Special cases:
- Wind / Solar / Storage:Battery → FOR=0, FORLength=1, MOR=0
"""

import os
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT  = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"
RESOURCES_CSV = DATA_CLEANING / "resources" / "colorado_resources.csv"
EIA860_ZIP    = DATA_CLEANING / "resources" / "eia860" / "raw" / "eia860_2024.zip"
GADS_XLSX     = (
    DATA_CLEANING / "resources" / "nercgads"
    / "generating-unit-statistical-brochure-4-2020---2024---all-units-reporting.xlsx"
)
GADS_SHEET = "2024-04"

# GADS brochure column indices (0-based, header=None read)
_GADS_CAT   =  0
_GADS_UYRR  =  4
_GADS_FOH   = 15
_GADS_N_FOH = 16
_GADS_MOF   = 32
_GADS_EFORd = 42

# Map our TechType labels -> GADS base category name (without size suffix)
GADS_TECH_BASE: dict[str, str] = {
    "Coal":         "FOSSIL  Coal Primary",
    "Gas:CC":       "COMBINED CYCLE",
    "Gas:CT":       "GAS TURBINE",
    "Gas:ST":       "FOSSIL  Gas Primary",
    "Gas:IC":       "JET ENGINE",
    "Nuclear":      "NUCLEAR All Types",
    "Hydro":        "HYDRO",
    "Hydro:Pumped": "PUMPED STORAGE",
}

ZERO_OUTAGE_TECHS = {"Wind", "Solar:PV", "Solar:CSP", "Storage:Battery"}


# ---------------------------------------------------------------------------
# MinCap — EIA-860
# ---------------------------------------------------------------------------

def load_eia860_min_load(zip_path: Path) -> pd.DataFrame:
    gen_file = "3_1_Generator_Y2024.xlsx"
    print(f"\n[MinCap] Loading EIA-860 minimum load from {zip_path.name}")

    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(gen_file) as f:
            df = pd.read_excel(
                BytesIO(f.read()),
                sheet_name="Operable",
                header=1,
                usecols=[
                    "Plant Code", "Generator ID",
                    "Nameplate Capacity (MW)", "Minimum Load (MW)",
                ],
            )

    df = df.rename(columns={
        "Plant Code":              "plant_code",
        "Generator ID":            "generator_id",
        "Nameplate Capacity (MW)": "nameplate_mw",
        "Minimum Load (MW)":       "min_load_mw",
    })

    df["plant_code"]   = pd.to_numeric(df["plant_code"],   errors="coerce")
    df["min_load_mw"]  = pd.to_numeric(df["min_load_mw"],  errors="coerce")
    df["nameplate_mw"] = pd.to_numeric(df["nameplate_mw"], errors="coerce")

    df = df.dropna(subset=["plant_code", "generator_id", "nameplate_mw"])
    df["plant_code"]   = df["plant_code"].astype(int)
    df["generator_id"] = df["generator_id"].astype(str).str.strip()

    print(f"  Loaded {len(df):,} operable generators")
    return df.set_index(["plant_code", "generator_id"])


def assign_min_cap(resources: pd.DataFrame, eia860: pd.DataFrame) -> pd.DataFrame:
    print("\n[MinCap] Assigning ...")

    resources = resources.copy()
    resources["MinCap"]        = pd.NA
    resources["mincap_source"] = pd.NA

    matched_eia  = 0
    must_run     = 0
    battery_zero = 0

    # Pass 1: EIA-860 plant-level lookup + must-run / storage special cases
    for idx, row in resources.iterrows():
        tech    = row.get("TechType", "")
        max_cap = float(row.get("MaxCap", 0) or 0)

        if tech in {"Wind", "Solar:PV", "Solar:CSP"}:
            resources.at[idx, "MinCap"]        = round(max_cap, 2)
            resources.at[idx, "mincap_source"] = "must_run_maxcap"
            must_run += 1
            continue

        if tech == "Storage:Battery":
            resources.at[idx, "MinCap"]        = 0.0
            resources.at[idx, "mincap_source"] = "storage_zero"
            battery_zero += 1
            continue

        raw_codes = row.get("plant_codes")
        raw_gens  = row.get("generator_ids")
        if pd.isna(raw_codes) or pd.isna(raw_gens):
            continue

        codes = [int(c.strip()) for c in str(raw_codes).split(";") if c.strip()]
        gens  = [g.strip() for g in str(raw_gens).split(";") if g.strip()]

        matched_rows = []
        for code in codes:
            for gen in gens:
                key = (code, gen)
                if key in eia860.index:
                    matched_rows.append(eia860.loc[key])

        if matched_rows:
            sub             = pd.DataFrame(matched_rows)
            total_nameplate = sub["nameplate_mw"].sum()
            total_min_load  = sub["min_load_mw"].fillna(0).sum()
            if total_nameplate > 0:
                pmin_frac = total_min_load / total_nameplate
                resources.at[idx, "MinCap"]        = round(pmin_frac * max_cap, 2)
                resources.at[idx, "mincap_source"] = "eia860_2024"
                matched_eia += 1

    # Pass 2: CO fleet cap-wtd average fallback for unmatched resources
    eia_matched = resources[resources["mincap_source"] == "eia860_2024"].copy()
    eia_matched["pmin_frac"] = eia_matched["MinCap"] / eia_matched["MaxCap"]
    tech_avg_pmin: dict[str, float] = (
        eia_matched.groupby("TechType")
        .apply(lambda g: (g["pmin_frac"] * g["MaxCap"]).sum() / g["MaxCap"].sum(), include_groups=False)
        .to_dict()
    )

    fallback_tech = 0
    no_match      = 0
    for idx, row in resources.iterrows():
        if pd.notna(row.get("mincap_source")):
            continue
        tech    = row.get("TechType", "")
        max_cap = float(row.get("MaxCap", 0) or 0)
        if tech in tech_avg_pmin:
            pmin_frac = tech_avg_pmin[tech]
            resources.at[idx, "MinCap"]        = round(pmin_frac * max_cap, 2)
            resources.at[idx, "mincap_source"] = "eia860_co_avg"
            fallback_tech += 1
        else:
            no_match += 1

    print(f"  EIA-860 plant-level match : {matched_eia}")
    print(f"  CO fleet average fallback : {fallback_tech}")
    print(f"  Wind/Solar must-run       : {must_run}")
    print(f"  Battery (zero MinCap)     : {battery_zero}")
    if no_match:
        print(f"  No match / not set        : {no_match}")

    print(f"\n  Cap-wtd avg Pmin by TechType (fallback fractions):")
    for tech, frac in sorted(tech_avg_pmin.items()):
        print(f"    {tech:<18} {frac:.1%}")

    return resources


# ---------------------------------------------------------------------------
# Outage Rates — NERC GADS
# ---------------------------------------------------------------------------

def _parse_size_range(suffix: str) -> tuple[float, float]:
    """Return (lo, hi) MW for a GADS size-bin suffix string."""
    s = suffix.strip()
    if s == "All Sizes":
        return (0.0, float("inf"))
    m = re.match(r"(\d+)\s*Plus", s)
    if m:
        return (float(m.group(1)), float("inf"))
    m = re.match(r"(\d+)\s*[-–]\s*(\d+)", s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    return (0.0, float("inf"))


def _best_bin(gads: pd.DataFrame, base: str, mw_per_unit: float) -> str | None:
    """
    Return the tightest GADS category whose size range contains mw_per_unit.
    Falls back to the 'All Sizes' row if no sized bin matches.
    """
    candidates = [cat for cat in gads.index if cat.startswith(base)]
    if not candidates:
        return None
    all_sizes = next((c for c in candidates if "All Sizes" in c), None)
    for cat in candidates:
        if "All Sizes" in cat:
            continue
        lo, hi = _parse_size_range(cat[len(base):])
        if lo <= mw_per_unit <= hi:
            return cat
    return all_sizes


def load_gads_rates(xlsx_path: Path) -> pd.DataFrame:
    print(f"\n[Outage] Loading NERC GADS from {xlsx_path.name} / sheet '{GADS_SHEET}'")
    df = pd.read_excel(xlsx_path, sheet_name=GADS_SHEET, header=None)

    for col in [_GADS_UYRR, _GADS_FOH, _GADS_N_FOH, _GADS_MOF, _GADS_EFORd]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=[_GADS_UYRR, _GADS_EFORd, _GADS_MOF])
    df = df[df.index != 0]

    df["cat"]        = df[_GADS_CAT].astype(str).str.strip()
    df["efrd_pct"]   = df[_GADS_EFORd]
    df["mof_pct"]    = df[_GADS_MOF]
    df["unit_years"] = df[_GADS_UYRR]
    df["forl_days"]  = (df[_GADS_FOH] / df[_GADS_N_FOH] / 24).where(
        df[_GADS_N_FOH] > 0, other=1.0
    )

    result = df.set_index("cat")[["efrd_pct", "forl_days", "mof_pct", "unit_years"]]
    print(f"  Loaded {len(result)} GADS category rows")
    return result


def assign_outage_rates(resources: pd.DataFrame, gads: pd.DataFrame) -> pd.DataFrame:
    print("\n[Outage] Assigning FOR / FORLength / MOR (size-bin matched) ...")

    resources = resources.copy()
    resources["FOR"]       = pd.NA
    resources["FORLength"] = pd.NA
    resources["MOR"]       = pd.NA
    resources["gads_bin"]  = pd.NA

    gads_count  = 0
    zero_count  = 0
    unset_count = 0

    for idx, row in resources.iterrows():
        tech    = row.get("TechType", "")
        max_cap = float(row.get("MaxCap", 0) or 0)
        units   = int(row.get("Units", 1) or 1)
        mw_unit = max_cap / units if units > 0 else 0.0

        if tech in ZERO_OUTAGE_TECHS:
            resources.at[idx, "FOR"]       = 0.0
            resources.at[idx, "FORLength"] = 1.0
            resources.at[idx, "MOR"]       = 0.0
            resources.at[idx, "gads_bin"]  = "zero_outage"
            zero_count += 1
            continue

        base = GADS_TECH_BASE.get(tech)
        if base is None:
            unset_count += 1
            continue

        cat = _best_bin(gads, base, mw_unit)
        if cat is None:
            unset_count += 1
            continue

        r = gads.loc[cat]
        resources.at[idx, "FOR"]       = round(float(r["efrd_pct"]), 2)
        resources.at[idx, "FORLength"] = round(float(r["forl_days"]), 2)
        resources.at[idx, "MOR"]       = round(float(r["mof_pct"]), 2)
        resources.at[idx, "gads_bin"]  = cat
        gads_count += 1

    print(f"  GADS size-bin assignment   : {gads_count}")
    print(f"  Zero outage (RE/storage)   : {zero_count}")
    if unset_count:
        unmatched = resources[resources["FOR"].isna()]["TechType"].unique()
        print(f"  Unmatched TechTypes        : {unset_count}  -> {list(unmatched)}")

    return resources


# ---------------------------------------------------------------------------
# Word table export
# ---------------------------------------------------------------------------

def export_word_table(resources: pd.DataFrame, out_path: Path) -> None:
    """
    Write a tab-separated table with one row per unique GADS bin.
    Outage rates are identical within a bin; MinCap % is the
    capacity-weighted average across resources in the bin.
    Open the file, select all, copy, paste into Word — tabs become
    column separators automatically.
    """
    thermal_hydro = set(GADS_TECH_BASE.keys())
    sub = resources[resources["TechType"].isin(thermal_hydro)].copy()

    def wtd_avg(grp: pd.DataFrame, col: str) -> float:
        cap = grp["MaxCap"]
        return (grp[col] * cap).sum() / cap.sum() if cap.sum() > 0 else float("nan")

    tech_rows = []
    for tech, grp in sub.groupby("TechType"):
        tech_rows.append({
            "Technology":           tech,
            "FOR (%)":              round(wtd_avg(grp, "FOR"),       2),
            "FOR Duration (days)":  round(wtd_avg(grp, "FORLength"), 2),
            "MOR (%)":              round(wtd_avg(grp, "MOR"),       2),
        })

    tech_df = pd.DataFrame(tech_rows).sort_values("Technology")

    headers = list(tech_df.columns)

    def fmt(val, decimals=2):
        return f"{val:.{decimals}f}" if pd.notna(val) else "-"

    lines = ["\t".join(headers)]
    for _, row in tech_df.iterrows():
        lines.append("\t".join([
            str(row["Technology"]),
            fmt(row["FOR (%)"],             2),
            fmt(row["FOR Duration (days)"], 2),
            fmt(row["MOR (%)"],             2),
        ]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Word table saved : {out_path}")
    print(f"  Rows exported    : {len(tech_df)} tech types")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def print_diagnostic_table(resources: pd.DataFrame) -> None:
    print("\n--- MinCap and outage rate summary ---")
    print(
        f"  {'Name':<52} {'Tech':<16} {'MW/unit':>7} "
        f"{'MinCap':>7} {'Pmin%':>6}  {'FOR%':>5} {'FORLen':>6} {'MOR%':>5}  "
        f"{'GADS bin':<44} {'MinCap src':<20}"
    )
    print(f"  {'-'*172}")

    for _, row in resources.iterrows():
        name    = str(row["Name"])[:52]
        tech    = str(row.get("TechType", ""))[:16]
        max_cap = float(row.get("MaxCap", 0) or 0)
        units   = int(row.get("Units", 1) or 1)
        mw_unit = max_cap / units if units > 0 else 0.0
        min_cap = row.get("MinCap")
        src     = str(row.get("mincap_source", ""))[:20]
        for_v   = row.get("FOR")
        forl_v  = row.get("FORLength")
        mor_v   = row.get("MOR")
        gbin    = str(row.get("gads_bin", ""))[:44]

        pmin_pct  = (
            f"{min_cap / max_cap * 100:>5.0f}%"
            if pd.notna(min_cap) and max_cap > 0
            else "    -"
        )
        min_cap_s = f"{min_cap:>7.1f}" if pd.notna(min_cap) else "      -"
        for_s     = f"{for_v:>5.2f}" if pd.notna(for_v) else "    -"
        forl_s    = f"{forl_v:>6.2f}" if pd.notna(forl_v) else "     -"
        mor_s     = f"{mor_v:>5.2f}" if pd.notna(mor_v) else "    -"

        print(
            f"  {name:<52} {tech:<16} {mw_unit:>7.1f} "
            f"{min_cap_s} {pmin_pct}  {for_s} {forl_s} {mor_s}  "
            f"{gbin:<44} {src:<20}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Script 17: MinCap and Outage Rates ===")

    resources = pd.read_csv(RESOURCES_CSV)
    print(f"  Loaded {len(resources)} resources from {RESOURCES_CSV.name}")

    stale_cols = [
        c for c in
        ["MinCap", "mincap_source", "FOR", "FORLength", "MOR", "gads_bin"]
        if c in resources.columns
    ]
    if stale_cols:
        resources = resources.drop(columns=stale_cols)
        print(f"  Dropped stale columns: {stale_cols}")

    eia860 = load_eia860_min_load(EIA860_ZIP)
    resources = assign_min_cap(resources, eia860)

    gads = load_gads_rates(GADS_XLSX)
    resources = assign_outage_rates(resources, gads)

    print_diagnostic_table(resources)

    resources.to_csv(RESOURCES_CSV, index=False)
    print(f"\n  Saved: {RESOURCES_CSV}")
    print(f"  New columns: MinCap, mincap_source, FOR, FORLength, MOR, gads_bin")

    word_table_path = DATA_CLEANING / "resources" / "nercgads" / "21_mincap_outage_rates.txt"
    export_word_table(resources, word_table_path)


if __name__ == "__main__":
    main()
