"""
PyPSA Milestone 1: load & renewable CF time-series assembly.

Turns two data_cleaning/ outputs into time series shaped for PyPSA's loads_t.p_set /
generators_t.p_max_pu -- not yet attached to a live Network (no buses/generators exist yet;
that's Milestone 5). See pypsa/Documentation/build_plan.md for full milestone context.

Snapshot calendar is 2018 throughout (the only year the calibrated CF profiles exist for, and
the same hourly shape the load data is built from) -- target_year is purely a scaling/lookup
parameter, not the calendar the snapshots are labeled with.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root
from model_helpers import WIND_ZONE_POINTS

PROJECT_ROOT = find_project_root()
LOAD_DIR = PROJECT_ROOT / "data_cleaning" / "load"
SHAPES_DIR = PROJECT_ROOT / "data_cleaning" / "solar_wind_shapes"
OUT_DIR = PROJECT_ROOT / "pypsa" / "diagnostics"

HOURLY_LOAD_PATH = LOAD_DIR / "zone_sector_hourly_load_mw_2025.csv"
GROWTH_PATH = LOAD_DIR / "I_zt_load_forecast_indices_CO_through_2050.csv"
SOLAR_CF_PATH = SHAPES_DIR / "solar_cf_calibrated.csv"
WIND_CF_PATH = SHAPES_DIR / "wind_cf_calibrated.csv"

BASE_YEAR = 2025
ZONES = ["Denver", "East", "Mountain", "North", "South", "West"]

# Source column -> clean output column. The zone/point structure comes from model_helpers'
# WIND_ZONE_POINTS (shared with Milestone 4's candidate siting, extracted 2026-08-15 the first
# time that structure was needed a second place); the source-file naming pattern
# ("{zone}_2018_wind_point{n}_cf") is specific to this one CSV, so stays local rather than also
# being pushed into the shared module. North/South wind keep a "_pt1" suffix even though they
# only have one point, for structural consistency with East's 3 points -- avoids downstream code
# needing to special-case "does this zone have one wind point or several."
SOLAR_COLUMN_MAP = {f"{zone}_cf": f"{zone}_solar_cf" for zone in ZONES}
WIND_COLUMN_MAP = {
    f"{zone}_2018_wind_point{pt}_cf": f"{zone}_wind_pt{pt}_cf"
    for zone, points in WIND_ZONE_POINTS.items()
    for pt in points
}


def build_load_timeseries(target_year: int) -> pd.DataFrame:
    """Zone-aggregate hourly MW load, scaled from the 2025 base year (Script 27's output) to
    target_year, indexed by 2018-dated hourly timestamps.

    zone_sector_hourly_load_mw_2025.csv is already scaled once, from zone_sector_ehat_CO_2024.csv's
    raw 2024 energy up to the formal 2025 base year, via net_demand_forecast_mwh_idx at
    forecast_year == 2025 (Script 27's own logic). Scaling to target_year from here means the
    *ratio* of that year's index to the 2025 index, not target_year's index alone -- applying
    idx[target_year] directly to the already-2025-scaled values would apply the index twice.
    """
    hourly_2025 = pd.read_csv(HOURLY_LOAD_PATH, index_col="hour")
    growth = pd.read_csv(GROWTH_PATH)

    result = pd.DataFrame(index=pd.date_range("2018-01-01", periods=8760, freq="h"))
    result.index.name = "snapshot"

    for zone in ZONES:
        idx_target = float(
            growth.loc[
                (growth["zone"] == zone) & (growth["forecast_year"] == target_year),
                "net_demand_forecast_mwh_idx",
            ].iloc[0]
        )
        idx_base = float(
            growth.loc[
                (growth["zone"] == zone) & (growth["forecast_year"] == BASE_YEAR),
                "net_demand_forecast_mwh_idx",
            ].iloc[0]
        )
        scale = idx_target / idx_base
        result[zone] = hourly_2025[f"{zone}_mw"].values * scale

    return result


def build_cf_timeseries() -> pd.DataFrame:
    """Solar + wind capacity factors, combined into one tidy table indexed by the same 2018
    hourly snapshots build_load_timeseries() uses.

    Source files use different literal timestamps for the "same" hour -- solar is stamped at
    :30 past the hour, wind at :00 -- documented in encompass/scripts/3's own docstring as the
    same underlying data. A literal datetime-value join would silently produce mismatches
    (solar's :30 stamps don't line up with an on-the-hour index at all). Read both by row
    position instead (values, not the source datetime index) and assign our own canonical
    on-the-hour index -- same fix that script already applies for the same reason.
    """
    solar = pd.read_csv(SOLAR_CF_PATH, index_col="datetime")
    wind = pd.read_csv(WIND_CF_PATH, index_col="datetime")

    if len(solar) != 8760 or len(wind) != 8760:
        raise ValueError(f"Expected 8760 hourly rows, got solar={len(solar)}, wind={len(wind)}")

    snapshots = pd.date_range("2018-01-01", periods=8760, freq="h")
    result = pd.DataFrame(index=snapshots)
    result.index.name = "snapshot"

    for src_col, out_col in SOLAR_COLUMN_MAP.items():
        result[out_col] = solar[src_col].values
    for src_col, out_col in WIND_COLUMN_MAP.items():
        result[out_col] = wind[src_col].values

    return result


def main() -> None:
    print("\n--- PyPSA Milestone 1: load + CF timeseries ---")

    test_year = 2030
    print(f"\n[Load] target_year={test_year} (placeholder, not the real pilot year)...")
    load_2030 = build_load_timeseries(test_year)
    load_2025 = build_load_timeseries(2025)

    print(f"Shape: {load_2030.shape} (expect (8760, 6))")
    print(f"Index: {load_2030.index[0]} .. {load_2030.index[-1]}")

    print(f"\nAnnual energy by zone (GWh):")
    print(f"{'zone':10s} {'2025':>10s} {'2030':>10s} {'ratio':>8s}")
    for zone in ZONES:
        gwh_2025 = load_2025[zone].sum() / 1000.0
        gwh_2030 = load_2030[zone].sum() / 1000.0
        print(f"{zone:10s} {gwh_2025:10,.1f} {gwh_2030:10,.1f} {gwh_2030/gwh_2025:8.4f}")

    print("\n[CF] building solar + wind capacity factor timeseries...")
    cf = build_cf_timeseries()

    print(f"Shape: {cf.shape} (expect (8760, 11) -- 6 solar + 5 wind)")
    print(f"Index: {cf.index[0]} .. {cf.index[-1]}")
    print(f"Columns: {list(cf.columns)}")

    out_of_range = cf[(cf < 0) | (cf > 1)].dropna(how="all")
    if len(out_of_range):
        raise ValueError(f"CF values outside [0,1] found:\n{out_of_range}")
    print("All values in [0, 1]: OK")

    print("\nSpot-check against source files (position-based, first 2 rows):")
    solar_raw = pd.read_csv(SOLAR_CF_PATH, index_col="datetime")
    wind_raw = pd.read_csv(WIND_CF_PATH, index_col="datetime")
    checks = [
        ("Denver_solar_cf", solar_raw["Denver_cf"]),
        ("East_wind_pt2_cf", wind_raw["East_2018_wind_point2_cf"]),
    ]
    for out_col, src_series in checks:
        match = (cf[out_col].values[:2] == src_series.values[:2]).all()
        print(f"  {out_col}: cf={cf[out_col].values[:2]} src={src_series.values[:2]} match={match}")
        if not match:
            raise ValueError(f"{out_col} does not match its source column -- misalignment")

    print(f"\nAnnual mean CF by resource:")
    for col in cf.columns:
        print(f"  {col:20s} {cf[col].mean():.4f}")

    # CSV checkpoints -- for human inspection only, not read back in by any later step.
    # build_load_timeseries() is called directly by Milestone 2 (load shape reconciliation) and
    # Milestone 5 (single-year pilot, not yet rewired to go through Milestone 2/3);
    # build_cf_timeseries() directly by Milestone 3 (representative periods) and Milestone 5.
    # None of them read these CSVs back in: load is parameterized by target_year, so a single
    # cached CSV could only ever represent one year and would go stale the moment a different
    # year is needed -- exactly the file-per-year problem Script 27 deliberately avoided by not
    # materializing every year in the first place. Regenerated fresh each run; not hand-edited.
    print(f"\nSaving inspection checkpoints to {OUT_DIR.relative_to(PROJECT_ROOT)}...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    load_out_path = OUT_DIR / f"load_timeseries_{test_year}.csv"
    cf_out_path = OUT_DIR / "cf_timeseries.csv"
    load_2030.to_csv(load_out_path)
    cf.to_csv(cf_out_path)
    print(f"  {load_out_path.name}")
    print(f"  {cf_out_path.name}")


if __name__ == "__main__":
    main()
