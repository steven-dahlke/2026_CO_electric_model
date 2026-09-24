import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root
from solar_wind_utils import (
    PARAMS, FARM, ATB_T1,
    parse_nsrdb, run_pvwatts,
    build_power_curve, parse_bchrrr, run_windpower,
)

"""
Script 12: Calibrate 2018 AMY solar and wind capacity factor profiles to
long-term average (LTA) resource levels.

Solar  — Runs PVWatts V8 on NSRDB TMY (tmy-2024) for each zone centroid.
         TMY annual CF is the LTA reference for that zone.

Wind   — Runs SAM Windpower on BC-HRRR for all 9 years (2015-2023) per point.
         The 9-year mean annual CF is the LTA reference for each point.

Calibration method: multiply each hour of the 2018 profile by a scalar
  scale_factor = LTA_CF / 2018_CF
preserving the hourly shape while matching the long-term average level.
Values are capped at 1.0; hours clipped are reported.

Requires:
  data_cleaning/solar_wind_shapes/raw/solar/{Zone}_tmy_solar.csv   (from script 14)
  data_cleaning/solar_wind_shapes/raw/wind/{Zone}_{year}_wind_point{n}.csv (scripts 10 + 14)
  data_cleaning/solar_wind_shapes/solar_cf_profiles.csv            (from script 12)
  data_cleaning/solar_wind_shapes/wind_cf_profiles.csv             (from script 13)

Outputs:
  data_cleaning/solar_wind_shapes/solar_cf_calibrated.csv
  data_cleaning/solar_wind_shapes/wind_cf_calibrated.csv
  data_cleaning/solar_wind_shapes/calibration_factors.csv
"""

PROJECT_ROOT  = find_project_root()
SHAPES_DIR    = PROJECT_ROOT / "data_cleaning" / "solar_wind_shapes"
RAW_SOLAR_DIR = SHAPES_DIR / "raw" / "solar"
RAW_WIND_DIR  = SHAPES_DIR / "raw" / "wind"

SOLAR_2018_PATH = SHAPES_DIR / "solar_cf_profiles.csv"
WIND_2018_PATH  = SHAPES_DIR / "wind_cf_profiles.csv"
SOLAR_OUT_PATH  = SHAPES_DIR / "solar_cf_calibrated.csv"
WIND_OUT_PATH   = SHAPES_DIR / "wind_cf_calibrated.csv"
FACTORS_PATH    = SHAPES_DIR / "calibration_factors.csv"

SOLAR_ZONES = ["Denver", "East", "Mountain", "North", "South", "West"]

WIND_POINTS = {
    "North": [1],
    "East":  [1, 2, 3],
    "South": [1],
}

# All 9 BC-HRRR years used for wind LTA (2018 is the shape year; all 9 used for mean)
WIND_YEARS = [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023]


# ---------------------------------------------------------------------------
# Solar LTA: run PVWatts on TMY file for each zone
# ---------------------------------------------------------------------------

def compute_solar_tmy_cfs() -> dict[str, float]:
    """Return {zone: TMY annual CF} by running PVWatts on each TMY file."""
    print("Computing solar TMY capacity factors...")
    tmy_cfs = {}
    for zone in SOLAR_ZONES:
        path = RAW_SOLAR_DIR / f"{zone}_tmy_solar.csv"
        if not path.exists():
            raise FileNotFoundError(
                f"TMY solar file not found: {path}\n"
                "Run script 14 first to download TMY data."
            )
        resource, _ = parse_nsrdb(path)
        cf = run_pvwatts(resource, PARAMS)
        annual_cf = sum(cf) / len(cf)
        tmy_cfs[zone] = annual_cf
        print(f"  {zone}: TMY annual CF = {annual_cf:.4f}")
    return tmy_cfs


# ---------------------------------------------------------------------------
# Wind LTA: run SAM Windpower on all 9 years for each point, then average
# ---------------------------------------------------------------------------

def compute_wind_lta_cfs(curve_speeds: tuple, curve_power: tuple) -> dict[str, float]:
    """Return {point_name: 9-year mean annual CF} across all BC-HRRR years."""
    print("\nComputing wind LTA capacity factors (9-year mean, 2015-2023)...")
    lta_cfs = {}

    for zone, indices in WIND_POINTS.items():
        for idx in indices:
            col_name = f"{zone}_2018_wind_point{idx}_cf"
            annual_cfs = []

            for year in WIND_YEARS:
                path = RAW_WIND_DIR / f"{zone}_{year}_wind_point{idx}.csv"
                if not path.exists():
                    print(f"  [warn] missing: {path.name} -- skipping year {year}")
                    continue
                resource, _ = parse_bchrrr(path)
                cf = run_windpower(resource, curve_speeds, curve_power, FARM)
                annual_cf = sum(cf) / len(cf)
                annual_cfs.append(annual_cf)

            if not annual_cfs:
                raise RuntimeError(f"No wind files found for {zone} point {idx}.")

            lta_cf = float(np.mean(annual_cfs))
            lta_cfs[col_name] = lta_cf
            print(f"  {zone} pt{idx}: {len(annual_cfs)}-year mean CF = {lta_cf:.4f}  "
                  f"(range {min(annual_cfs):.3f}-{max(annual_cfs):.3f})")

    return lta_cfs


# ---------------------------------------------------------------------------
# Apply scale factors and write outputs
# ---------------------------------------------------------------------------

def calibrate_and_save(
    profiles_2018: pd.DataFrame,
    col_to_lta: dict[str, float],
    col_to_2018: dict[str, float],
    output_path: Path,
    resource_type: str,
) -> list[dict]:
    """Scale 2018 profiles, cap at 1.0, save, return calibration factor records."""
    calibrated = profiles_2018.copy()
    records = []

    for col, lta_cf in col_to_lta.items():
        cf_2018 = col_to_2018[col]
        scale   = lta_cf / cf_2018

        scaled = profiles_2018[col] * scale
        clipped_hours = int((scaled > 1.0).sum())
        scaled = scaled.clip(upper=1.0)

        calibrated[col] = scaled
        records.append({
            "resource":     resource_type,
            "site":         col,
            "cf_2018":      round(cf_2018, 5),
            "cf_lta":       round(lta_cf, 5),
            "scale_factor": round(scale, 5),
            "hours_clipped": clipped_hours,
        })
        print(f"  {col}: scale={scale:.4f}  "
              f"({cf_2018:.4f} -> {lta_cf:.4f})  "
              f"clipped={clipped_hours}h")

    calibrated.to_csv(output_path)
    print(f"  Saved -> {output_path.name}")
    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # --- Solar ---
    print("=" * 60)
    print("SOLAR CALIBRATION")
    print("=" * 60)

    solar_2018 = pd.read_csv(SOLAR_2018_PATH, index_col="datetime", parse_dates=True)
    solar_tmy_cfs = compute_solar_tmy_cfs()

    solar_2018_cfs = {
        f"{zone}_cf": solar_2018[f"{zone}_cf"].mean()
        for zone in SOLAR_ZONES
    }
    solar_lta_cfs = {f"{zone}_cf": v for zone, v in solar_tmy_cfs.items()}

    print("\nApplying solar scale factors...")
    solar_records = calibrate_and_save(
        solar_2018, solar_lta_cfs, solar_2018_cfs, SOLAR_OUT_PATH, "solar"
    )

    # --- Wind ---
    print("\n" + "=" * 60)
    print("WIND CALIBRATION")
    print("=" * 60)

    print("\nBuilding ATB 2024 T1 power curve...")
    curve_speeds, curve_power = build_power_curve(ATB_T1)
    print(f"  Curve: {len(curve_speeds)} points, max {max(curve_power):.0f} kW")

    wind_2018 = pd.read_csv(WIND_2018_PATH, index_col="datetime", parse_dates=True)
    wind_lta_cfs = compute_wind_lta_cfs(curve_speeds, curve_power)

    wind_2018_cfs = {col: wind_2018[col].mean() for col in wind_lta_cfs}

    print("\nApplying wind scale factors...")
    wind_records = calibrate_and_save(
        wind_2018, wind_lta_cfs, wind_2018_cfs, WIND_OUT_PATH, "wind"
    )

    # --- Summary table ---
    all_records = solar_records + wind_records
    factors_df = pd.DataFrame(all_records)
    factors_df.to_csv(FACTORS_PATH, index=False)
    print(f"\nCalibration factors saved -> {FACTORS_PATH.name}")

    print("\nCalibration summary:")
    print(factors_df.to_string(index=False))


if __name__ == "__main__":
    main()
