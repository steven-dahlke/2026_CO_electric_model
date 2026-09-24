"""
Script 18: Storage Parameters — PaybckReq, MaxStorage, PaybckCap

Enriches colorado_resources.csv (Script 17 output) with:
  - PaybckReq (%) — storage efficiency parameter
  - MaxStorage (MWh) — energy storage capacity
  - PaybckCap (MW)  — charging / pumping power capacity

New columns: PaybckReq, MaxStorage, PaybckCap

────────────────────────────────────────────────────────────────────────────
PaybckReq  (NLR ATB 2024)
────────────────────────────────────────────────────────────────────────────
PaybckReq = 100 / round_trip_efficiency (%)

Storage:Battery
  RTE = 85% (AC-AC), flat across all durations and scenarios.
  Source: NLR ATB 2024, Utility-Scale Battery Storage.
  PaybckReq = 117.65%

Hydro:Pumped
  RTE = 80%, based on Mongird et al. (2020) central estimate.
  Source: NLR ATB 2024, Pumped Storage Hydropower.
  PaybckReq = 125.0%

────────────────────────────────────────────────────────────────────────────
MaxStorage  (MWh) — per EnCompass unit
────────────────────────────────────────────────────────────────────────────
Storage:Battery
  Carried forward from EIA-860 energy storage sheet (max_energy_mwh column),
  assigned in an earlier script.  Not recomputed here.

Hydro:Pumped — lookup table, one entry per resource:

  cabin_creek__A / B  680 MWh / unit
    Source: Electric Energy Online, "Hydro at 10,000 Feet: Modernizing the
    Renewable Infrastructure," Vol. 910 (web article, no page numbers).
    URL: electricenergyonline.com/energy/magazine/910/article/...
    Quote: "At full load, this equates to about four hours of running time."
    Applied as 4 hr x 170 MW (EIA-860 summer capacity) = 680 MWh per unit.
    Note: article was written at original 162 MW rating; the 4-hour duration
    is assumed to carry forward to the upgraded 170 MW rating.

  mount_elbert__1 / 2  calculated
    E (MWh) = 1.024 x active_storage_AF x head_ft x gen_efficiency / units

    Active storage: 275 acres x 31 ft drawdown = 8,525 AF
      Source: CLUI (Center for Land Use Interpretation), "Mount Elbert Pumped
      Storage Plant." clui.org/ludb/site/mount-elbert-pumped-storage-plant
      Quote: "The upper reservoir...is 275 acres in size, and fluctuates as
      much as 31 feet between being drawn down and filled up."

    Head: 448 ft  (read from ORNL EHA dataset by EIA plant 6208, gens 1 & 2)
      Source: Oak Ridge National Laboratory, Existing Hydropower Assets (EHA)
      Plant Dataset FY2026. hydrosource.ornl.gov/data/datasets/eha-unit-2026/
      File: ORNL_EHAHydroUnit_PublicFY2026.csv, Head_ft column.

    Generation efficiency: 90% (typical Francis turbine; no unit-specific source)
    Units sharing forebay: 2 (split equally)

    Result: 1.024 x 8,525 x 448 x 0.90 / 2 = 1,760 MWh per unit

  flatiron__3  203 MWh
    E = 0.001024 x active_storage_AF x head_ft x gen_efficiency / units

    Active storage: 760 AF (normal storage, Northern Water operating agency)
      Source: Northern Water, "Flatiron Reservoir."
      northernwater.org/water/projects/colorado-big-thompson-project/
      reservoirs-and-lakes/flatiron-reservoir
      Note: Flatiron Reservoir is a multi-purpose afterbay; 760 AF is the
      full normal storage, not a dedicated pump-back allocation. Unit is
      small (8.5 MW) so modeling impact of this uncertainty is minimal.

    Head: 290 ft  (ORNL EHA FY2026, plant 518, gen 3)
    Generation efficiency: 90% (assumed; same as Mount Elbert)

    Result: 0.001024 x 760 x 290 x 0.90 / 1 unit = 203 MWh

────────────────────────────────────────────────────────────────────────────
PaybckCap  (MW) — per EnCompass unit, charging / pump-mode power
────────────────────────────────────────────────────────────────────────────
Storage:Battery
  Carried forward from EIA-860 energy storage sheet (max_power_charge_mw
  column), assigned in an earlier script.  Not recomputed here.

Hydro:Pumped — lookup table, one entry per resource:

  cabin_creek__A / B  assumed = MaxCap (170 MW / unit)
    No primary source available for pump-mode capacity. Assumed equal to
    generating capacity. Physically reasonable: reversible Francis pump-turbines
    operate in both directions on the same machine; pump-mode power is typically
    within ~10-15% of generating capacity.

  mount_elbert__1 / 2  assumed = MaxCap (115 MW / unit)
    "170,000 HP Pump Mode" appeared in web search snippet summarizing USBR PDF
    (usbr.gov/projects/pdf.php?id=46), which was unreadable. Whether that
    figure is per unit or total plant is unresolved. Assumed = MaxCap pending
    confirmation from primary document.

  flatiron__3  9.7 MW
    Source: Power Technology, "Flatiron Hydroelectric Plant, USA"
    (power-technology.com/projects/flatiron/), readable HTML article.
    States "reversible 13,000 horsepower pump turbine unit."
    13,000 HP x 0.7457 kW/HP = 9,694 kW ≈ 9.7 MW.
"""

import os
import sys
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
ORNL_EHA_CSV  = (
    DATA_CLEANING / "resources" / "hydro"
    / "ORNL_EHAHydroUnit_PublicFY2026.csv"
)

# ---------------------------------------------------------------------------
# Mount Elbert forebay constants (for MaxStorage calculation)
# Forebay dimensions: CLUI, clui.org/ludb/site/mount-elbert-pumped-storage-plant
# Head: ORNL EHA FY2026, read at runtime by EIA plant/gen ID
# ---------------------------------------------------------------------------
MTELBERT_EIA_PLANT    = 6208
MTELBERT_EIA_GENS     = ["1", "2"]
MTELBERT_FOREBAY_AC   = 275    # acres
MTELBERT_DRAWDOWN_FT  = 31     # feet of water-level fluctuation
MTELBERT_GEN_EFF      = 0.90   # generation efficiency (typical Francis turbine)
MTELBERT_UNITS        = 2      # units sharing the forebay (equal split assumed)

# ---------------------------------------------------------------------------
# PaybckReq constants
# ---------------------------------------------------------------------------
BATTERY_RTE        = 0.85
BATTERY_PAYBCK_REQ = round(100 / BATTERY_RTE, 2)   # 117.65

PUMPED_RTE         = 0.80
PUMPED_PAYBCK_REQ  = round(100 / PUMPED_RTE, 2)    # 125.0

# ---------------------------------------------------------------------------
# Pumped hydro storage lookup
# Values are per EnCompass unit (resource row).
# Only values traceable to a readable primary or secondary source are included.
# Sources documented in module docstring above.
# Pending values (MaxStorage for all units) need primary-source verification.
# PaybckCap for Cabin Creek and Mount Elbert uses MaxCap fallback (see below).
# ---------------------------------------------------------------------------
PUMPED_STORAGE_PARAMS: dict[str, dict] = {
    # MaxStorage: 680 MWh — 4 hr x 170 MW (EIA-860 summer capacity).
    #   "At full load, this equates to about four hours of running time."
    #   Source: Electric Energy Online, "Hydro at 10,000 Feet: Modernizing the
    #   Renewable Infrastructure," Vol. 910.
    #   URL: electricenergyonline.com/energy/magazine/910/article/...
    #   Note: article was written when units were rated 162 MW (original); the
    #   4-hour duration is applied to the current 170 MW EIA-860 summer rating.
    # PaybckCap: assumed = MaxCap (reversible machine; no primary source).
    "cabin_creek__A": {
        "MaxStorage": 680.0,
        "PaybckCap":  None,
    },
    "cabin_creek__B": {
        "MaxStorage": 680.0,
        "PaybckCap":  None,
    },
    # MaxStorage: computed from forebay dimensions (CLUI) + ORNL EHA head.
    #   Value populated at runtime by calc_mtelbert_max_storage(); None here
    #   is a placeholder that gets overwritten before the assignment loop runs.
    # PaybckCap: assumed = MaxCap (reversible machine; no primary source).
    "mount_elbert__1": {
        "MaxStorage": None,   # filled at runtime
        "PaybckCap":  None,
    },
    "mount_elbert__2": {
        "MaxStorage": None,   # filled at runtime
        "PaybckCap":  None,
    },
    # MaxStorage: 203 MWh — E = 0.001024 x 760 AF x 290 ft x 0.90 / 1 unit
    #   Active storage: 760 AF (normal storage, Northern Water operating agency)
    #     northernwater.org/water/projects/colorado-big-thompson-project/
    #     reservoirs-and-lakes/flatiron-reservoir
    #   Head: 290 ft (ORNL EHA FY2026 plant 518 gen 3)
    #   Gen efficiency: 90% (assumed; same as Mt. Elbert)
    # PaybckCap: 9.7 MW — 13,000 HP pump motor; Power Technology Flatiron article
    #   (https://www.power-technology.com/projects/flatiron/), confirmed from
    #   readable HTML.
    "flatiron__3": {
        "MaxStorage": 203.0,
        "PaybckCap":  9.7,
    },
}


# ---------------------------------------------------------------------------
# ORNL EHA head loader and Mount Elbert MaxStorage calculator
# ---------------------------------------------------------------------------

def load_ornl_head(csv_path: Path) -> pd.DataFrame:
    """Return ORNL EHA rows indexed by (EIA_PtID, EIA_GnID) with Head_ft."""
    df = pd.read_csv(csv_path, encoding="latin-1", low_memory=False,
                     usecols=["EIA_PtID", "EIA_GnID", "Head_ft"])
    df["EIA_PtID"] = pd.to_numeric(df["EIA_PtID"], errors="coerce")
    df["EIA_GnID"] = df["EIA_GnID"].astype(str).str.strip()
    df["Head_ft"]  = pd.to_numeric(df["Head_ft"],  errors="coerce")
    return df


def calc_mtelbert_max_storage(ornl: pd.DataFrame) -> float:
    """
    Compute Mount Elbert MaxStorage (MWh per unit) from forebay dimensions
    and ORNL EHA head.

    Formula: E = 1.024 x active_storage_AF x head_ft x gen_efficiency / units
      where 1.024 kWh/(AF·ft) = rho*g/3,600,000 in US customary units.
    """
    mask  = (ornl["EIA_PtID"] == float(MTELBERT_EIA_PLANT)) & \
             ornl["EIA_GnID"].isin(MTELBERT_EIA_GENS)
    heads = ornl.loc[mask, "Head_ft"].dropna().tolist()

    if not heads:
        raise ValueError(
            f"No ORNL head found for plant {MTELBERT_EIA_PLANT} "
            f"gens {MTELBERT_EIA_GENS}"
        )

    head_ft         = sum(heads) / len(heads)   # average across gens (both 448)
    active_af       = MTELBERT_FOREBAY_AC * MTELBERT_DRAWDOWN_FT
    # 0.001024 MWh/(AF·ft) = rho*g / 3,600,000,000 in US customary units
    max_storage_mwh = (
        0.001024 * active_af * head_ft * MTELBERT_GEN_EFF / MTELBERT_UNITS
    )
    print(
        f"\n[MaxStorage] Mount Elbert calculation:"
        f"\n  Forebay active storage : {MTELBERT_FOREBAY_AC} acres x "
        f"{MTELBERT_DRAWDOWN_FT} ft = {active_af:,} AF  (CLUI)"
        f"\n  Head (ORNL EHA)        : {head_ft:.0f} ft  "
        f"(plant {MTELBERT_EIA_PLANT}, gens {MTELBERT_EIA_GENS})"
        f"\n  Generation efficiency  : {MTELBERT_GEN_EFF:.0%}  (assumed)"
        f"\n  Units sharing forebay  : {MTELBERT_UNITS}  (equal split assumed)"
        f"\n  MaxStorage per unit    : {max_storage_mwh:,.0f} MWh"
    )
    return round(max_storage_mwh, 0)


# ---------------------------------------------------------------------------
# Assignment functions
# ---------------------------------------------------------------------------

def assign_paybck_req(resources: pd.DataFrame) -> pd.DataFrame:
    print("\n[PaybckReq] Assigning ...")
    resources = resources.copy()
    resources["PaybckReq"] = pd.NA

    battery_count = 0
    pumped_count  = 0
    for idx, row in resources.iterrows():
        tech = row.get("TechType", "")
        if tech == "Storage:Battery":
            resources.at[idx, "PaybckReq"] = BATTERY_PAYBCK_REQ
            battery_count += 1
        elif tech == "Hydro:Pumped":
            resources.at[idx, "PaybckReq"] = PUMPED_PAYBCK_REQ
            pumped_count += 1

    print(f"  Storage:Battery ({BATTERY_RTE:.0%} RTE -> {BATTERY_PAYBCK_REQ}%) : {battery_count}")
    print(f"  Hydro:Pumped    ({PUMPED_RTE:.0%} RTE -> {PUMPED_PAYBCK_REQ}%) : {pumped_count}")
    return resources


def assign_pumped_storage(resources: pd.DataFrame) -> pd.DataFrame:
    print("\n[MaxStorage/PaybckCap] Assigning pumped hydro parameters ...")
    resources = resources.copy()

    if "MaxStorage" not in resources.columns:
        resources["MaxStorage"] = pd.NA
    if "PaybckCap" not in resources.columns:
        resources["PaybckCap"] = pd.NA

    # Reset pumped hydro rows first so stale values from prior runs don't persist
    ph_mask = resources["TechType"] == "Hydro:Pumped"
    resources.loc[ph_mask, "MaxStorage"] = pd.NA
    resources.loc[ph_mask, "PaybckCap"]  = pd.NA

    assigned = 0
    missing  = []
    for idx, row in resources.iterrows():
        if row.get("TechType") != "Hydro:Pumped":
            continue
        name = str(row["Name"])
        if name in PUMPED_STORAGE_PARAMS:
            p = PUMPED_STORAGE_PARAMS[name]
            if p["MaxStorage"] is not None:
                resources.at[idx, "MaxStorage"] = p["MaxStorage"]
            if p["PaybckCap"] is not None:
                resources.at[idx, "PaybckCap"] = p["PaybckCap"]
            assigned += 1
        else:
            missing.append(name)

    # Fallback: PaybckCap = MaxCap for pumped hydro rows still missing a value.
    # Rationale: reversible pump-turbines operate in both directions on the same
    # machine; pump-mode power is typically within ~10-15% of generating capacity.
    # Assumption documented here; update lookup table when primary source found.
    ph_null = resources["TechType"] == "Hydro:Pumped"
    ph_null_pbck = ph_null & resources["PaybckCap"].isna()
    if ph_null_pbck.any():
        resources.loc[ph_null_pbck, "PaybckCap"] = resources.loc[ph_null_pbck, "MaxCap"]
        assumed = resources.loc[ph_null_pbck, "Name"].tolist()
        print(f"  PaybckCap = MaxCap (assumed) : {len(assumed)}  -> {assumed}")

    print(f"  Assigned from lookup         : {assigned}")
    if missing:
        print(f"  *** No entry in lookup for  : {missing}")

    return resources


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def print_diagnostic_table(resources: pd.DataFrame) -> None:
    storage_techs = {"Storage:Battery", "Hydro:Pumped"}
    sub = resources[resources["TechType"].isin(storage_techs)].copy()

    print("\n--- Storage parameter summary ---")
    print(
        f"  {'Name':<44} {'Tech':<16} {'MaxCap':>7} "
        f"{'PaybckReq':>9} {'MaxStorage':>10} {'PaybckCap':>10}"
    )
    print(f"  {'-'*102}")

    for _, row in sub.iterrows():
        name  = str(row["Name"])[:44]
        tech  = str(row.get("TechType", ""))[:16]
        maxc  = row.get("MaxCap")
        pbr   = row.get("PaybckReq")
        mxst  = row.get("MaxStorage")
        pbck  = row.get("PaybckCap")

        maxc_s = f"{maxc:>7.1f}" if pd.notna(maxc) else "      -"
        pbr_s  = f"{pbr:>9.2f}" if pd.notna(pbr)  else "        -"
        mxst_s = f"{mxst:>10.1f}" if pd.notna(mxst) else "         -"
        pbck_s = f"{pbck:>10.1f}" if pd.notna(pbck) else "         -"

        print(f"  {name:<44} {tech:<16} {maxc_s} {pbr_s} {mxst_s} {pbck_s}")

    # Flag any remaining NaN storage columns
    pumped = resources[resources["TechType"] == "Hydro:Pumped"]
    null_mxst = pumped[pumped["MaxStorage"].isna()]["Name"].tolist()
    null_pbck = pumped[pumped["PaybckCap"].isna()]["Name"].tolist()
    if null_mxst:
        print(f"\n  *** MaxStorage still NaN for: {null_mxst}")
    if null_pbck:
        print(f"  *** PaybckCap still NaN for : {null_pbck}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Script 18: Storage Parameters ===")

    resources = pd.read_csv(RESOURCES_CSV)
    print(f"  Loaded {len(resources)} resources from {RESOURCES_CSV.name}")

    stale_cols = [c for c in ["PaybckReq"] if c in resources.columns]
    if stale_cols:
        resources = resources.drop(columns=stale_cols)
        print(f"  Dropped stale columns: {stale_cols}")

    ornl = load_ornl_head(ORNL_EHA_CSV)
    mtelbert_mwh = calc_mtelbert_max_storage(ornl)
    PUMPED_STORAGE_PARAMS["mount_elbert__1"]["MaxStorage"] = mtelbert_mwh
    PUMPED_STORAGE_PARAMS["mount_elbert__2"]["MaxStorage"] = mtelbert_mwh

    resources = assign_paybck_req(resources)
    resources = assign_pumped_storage(resources)

    print_diagnostic_table(resources)

    resources.to_csv(RESOURCES_CSV, index=False)
    print(f"\n  Saved: {RESOURCES_CSV}")
    print(f"  New/updated columns: PaybckReq, MaxStorage (pumped hydro), PaybckCap (pumped hydro)")


if __name__ == "__main__":
    main()
