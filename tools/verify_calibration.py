"""
Verification checks for data_cleaning/_scripts 11 and 12 outputs.
Run after script 12 completes. Prints a structured pass/fail report.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import find_project_root

PROJECT_ROOT  = find_project_root()
SHAPES_DIR    = PROJECT_ROOT / "data_cleaning" / "solar_wind_shapes"
RAW_SOLAR_DIR = SHAPES_DIR / "raw" / "solar"
RAW_WIND_DIR  = SHAPES_DIR / "raw" / "wind"

SOLAR_ZONES  = ["Denver", "East", "Mountain", "North", "South", "West"]
WIND_POINTS  = {"North": [1], "East": [1, 2, 3], "South": [1]}
WIND_YEARS   = [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023]

PASSES = []
FAILS  = []

def check(label: str, condition: bool, detail: str = ""):
    if condition:
        PASSES.append(f"  PASS  {label}" + (f" | {detail}" if detail else ""))
    else:
        FAILS.append(f"  FAIL  {label}" + (f" | {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# 1. Scripts 12/13 regression — CFs must exactly match pre-refactor values
# ---------------------------------------------------------------------------
print("\n[1] Scripts 12 & 13 regression (refactor must not change outputs)")

KNOWN_SOLAR = {"Denver": 0.2097, "East": 0.2207, "Mountain": 0.2063,
               "North": 0.2042, "South": 0.2306, "West": 0.2197}
KNOWN_WIND  = {"East_2018_wind_point1_cf": 0.5347,
               "East_2018_wind_point2_cf": 0.3668,
               "East_2018_wind_point3_cf": 0.4545,
               "North_2018_wind_point1_cf": 0.4732,
               "South_2018_wind_point1_cf": 0.2566}

solar_2018 = pd.read_csv(SHAPES_DIR / "solar_cf_profiles.csv", index_col="datetime")
for zone, expected in KNOWN_SOLAR.items():
    actual = round(solar_2018[f"{zone}_cf"].mean(), 4)
    check(f"Solar 2018 CF {zone}", actual == expected, f"expected {expected}, got {actual}")

wind_2018 = pd.read_csv(SHAPES_DIR / "wind_cf_profiles.csv", index_col="datetime")
for col, expected in KNOWN_WIND.items():
    actual = round(wind_2018[col].mean(), 4)
    check(f"Wind 2018 CF {col}", actual == expected, f"expected {expected}, got {actual}")


# ---------------------------------------------------------------------------
# 2. Script 14 file inventory
# ---------------------------------------------------------------------------
print("\n[2] Script 14 download completeness")

# TMY solar files
for zone in SOLAR_ZONES:
    path = RAW_SOLAR_DIR / f"{zone}_tmy_solar.csv"
    exists = path.exists()
    check(f"TMY solar file: {zone}", exists)
    if exists:
        nrows = sum(1 for _ in open(path)) - 3  # subtract 3 header rows
        check(f"TMY solar rows {zone}", nrows == 8760, f"got {nrows} data rows")

# Multi-year wind files
for zone, indices in WIND_POINTS.items():
    for idx in indices:
        for year in WIND_YEARS:
            path = RAW_WIND_DIR / f"{zone}_{year}_wind_point{idx}.csv"
            exists = path.exists()
            check(f"Wind file: {zone} pt{idx} {year}", exists)
            if exists:
                nrows = sum(1 for _ in open(path)) - 2  # 2 header rows
                check(f"Wind rows {zone} pt{idx} {year}", nrows == 8760, f"got {nrows}")


# ---------------------------------------------------------------------------
# 3. Script 15 calibration_factors.csv structure and plausibility
# ---------------------------------------------------------------------------
print("\n[3] Calibration factors plausibility")

factors = pd.read_csv(SHAPES_DIR / "calibration_factors.csv")
check("Factors row count", len(factors) == 11, f"got {len(factors)}, expected 11")
check("Factors columns present",
      {"resource","site","cf_2018","cf_lta","scale_factor","hours_clipped"}.issubset(factors.columns))

# Scale factors must be positive and not wildly out of range
sf = factors["scale_factor"]
check("All scale factors positive", (sf > 0).all(), f"min={sf.min():.4f}")
check("Scale factors in range 0.7-1.5", ((sf >= 0.7) & (sf <= 1.5)).all(),
      f"range [{sf.min():.4f}, {sf.max():.4f}]")

# No negative CFs
check("All cf_2018 positive", (factors["cf_2018"] > 0).all())
check("All cf_lta positive",  (factors["cf_lta"]  > 0).all())

# Solar LTA CFs should be within plausible range for Colorado (~0.18-0.28)
solar_factors = factors[factors["resource"] == "solar"]
check("Solar LTA CFs in range 0.18-0.28",
      ((solar_factors["cf_lta"] >= 0.18) & (solar_factors["cf_lta"] <= 0.28)).all(),
      f"range [{solar_factors['cf_lta'].min():.4f}, {solar_factors['cf_lta'].max():.4f}]")

# Wind LTA CFs should be within plausible range for CO (~0.20-0.60)
wind_factors = factors[factors["resource"] == "wind"]
check("Wind LTA CFs in range 0.20-0.60",
      ((wind_factors["cf_lta"] >= 0.20) & (wind_factors["cf_lta"] <= 0.60)).all(),
      f"range [{wind_factors['cf_lta'].min():.4f}, {wind_factors['cf_lta'].max():.4f}]")


# ---------------------------------------------------------------------------
# 4. Calibrated profile checks
# ---------------------------------------------------------------------------
print("\n[4] Calibrated profile integrity")

solar_cal = pd.read_csv(SHAPES_DIR / "solar_cf_calibrated.csv", index_col="datetime")
wind_cal  = pd.read_csv(SHAPES_DIR / "wind_cf_calibrated.csv",  index_col="datetime")

# Row counts
check("Solar calibrated rows", len(solar_cal) == 8760, f"got {len(solar_cal)}")
check("Wind calibrated rows",  len(wind_cal)  == 8760, f"got {len(wind_cal)}")

# Column names preserved
check("Solar calibrated columns",
      set(solar_cal.columns) == set(solar_2018.columns),
      f"got {sorted(solar_cal.columns)}")
check("Wind calibrated columns",
      set(wind_cal.columns) == set(wind_2018.columns),
      f"got {sorted(wind_cal.columns)}")

# No negative values
check("Solar calibrated no negatives", (solar_cal >= 0).all().all())
check("Wind calibrated no negatives",  (wind_cal  >= 0).all().all())

# Values capped at 1.0
check("Solar calibrated max <= 1.0", (solar_cal <= 1.0 + 1e-9).all().all(),
      f"max={solar_cal.max().max():.6f}")
check("Wind calibrated max <= 1.0",  (wind_cal  <= 1.0 + 1e-9).all().all(),
      f"max={wind_cal.max().max():.6f}")

# Calibrated annual CFs should match LTA CFs closely
# (small discrepancy expected only if hours were clipped)
for _, row in factors.iterrows():
    col = row["site"]
    df  = solar_cal if row["resource"] == "solar" else wind_cal
    actual_cal_cf = df[col].mean()
    tol = 0.005  # allow up to 0.5% absolute difference (from clipping)
    close = abs(actual_cal_cf - row["cf_lta"]) <= tol
    check(f"Calibrated CF matches LTA: {col}",
          close, f"LTA={row['cf_lta']:.4f} cal={actual_cal_cf:.4f} "
                 f"diff={abs(actual_cal_cf - row['cf_lta']):.4f}")

# Shape preservation: correlation between 2018 and calibrated must be ~1.0
for col in solar_2018.columns:
    r = solar_2018[col].corr(solar_cal[col])
    check(f"Solar shape preserved {col}", r > 0.9999, f"corr={r:.8f}")

for col in wind_2018.columns:
    r = wind_2018[col].corr(wind_cal[col])
    check(f"Wind shape preserved {col}", r > 0.9999, f"corr={r:.8f}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
print("\n" + "=" * 65)
total = len(PASSES) + len(FAILS)
print(f"RESULTS: {len(PASSES)} passed, {len(FAILS)} failed  ({total} total checks)")
print("=" * 65)

if FAILS:
    print("\nFAILURES:")
    for f in FAILS:
        print(f)

print("\nPASSED:")
for p in PASSES:
    print(p)

if not FAILS:
    print("\nAll checks passed.")
