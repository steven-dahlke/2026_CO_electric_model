import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root
from solar_wind_utils import PARAMS, parse_nsrdb, run_pvwatts, build_datetime_index

"""
Generate hourly solar AC capacity factor profiles for each Colorado zone using
NREL's PVWatts V8 model (via PySAM) with 2018 NSRDB actual meteorological year
(AMY) weather data. AMY is used to keep solar profiles temporally synchronized
with the 2018 load shapes used throughout this model.

Outputs a normalized capacity factor time series (AC kW per kW-DC installed)
for a representative utility-scale solar plant. Multiply by installed MW-DC to
get absolute generation in MWh.

Technology assumptions documented in PARAMS below represent mainstream
utility-scale solar in Colorado as of 2023-2025: premium monocrystalline
silicon modules (PERC/TOPCon) on single-axis trackers with a 1.2 DC-AC ratio.
See PARAMS comments for individual parameter rationale.

PVWatts is fully scaling-invariant: the normalized CF shape from 1 kW-DC is
identical to any other system size. Using 1 kW-DC makes the raw AC output in
watts numerically equal to the capacity factor.

Input:  data_cleaning/solar_wind_shapes/raw/solar/{Zone}_2018_solar.csv
Output: data_cleaning/solar_wind_shapes/solar_cf_profiles.csv
"""

PROJECT_ROOT = find_project_root()
RAW_SOLAR_DIR = PROJECT_ROOT / "data_cleaning" / "solar_wind_shapes" / "raw" / "solar"
OUTPUT_DIR = PROJECT_ROOT / "data_cleaning" / "solar_wind_shapes"
OUTPUT_PATH = OUTPUT_DIR / "solar_cf_profiles.csv"

ZONES = ["Denver", "East", "Mountain", "North", "South", "West"]


def main():
    results = {}
    datetime_index = None

    print("Running PVWatts V8 for each zone...")
    for zone in ZONES:
        path = RAW_SOLAR_DIR / f"{zone}_2018_solar.csv"
        print(f"  {zone}...", end=" ", flush=True)
        resource, df = parse_nsrdb(path)
        cf = run_pvwatts(resource)
        results[f"{zone}_cf"] = cf
        if datetime_index is None:
            datetime_index = build_datetime_index(df)
        annual_cf = sum(cf) / len(cf)
        print(f"annual CF = {annual_cf:.4f}  ({annual_cf * 8760:.0f} kWh/kW-DC/yr)")

    output = pd.DataFrame(results, index=datetime_index)
    output.index.name = "datetime"
    output.to_csv(OUTPUT_PATH)
    print(f"\nSaved {len(output)} rows x {len(output.columns)} zones -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
