import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root
from solar_wind_utils import ATB_T1, FARM, build_power_curve, parse_bchrrr, run_windpower, build_datetime_index

"""
Generate hourly wind AC capacity factor profiles for each BC-HRRR meteorological
data point using NREL's SAM Windpower model (via PySAM) with 2018 AMY wind data.
Profiles are on the same UTC-7 / 2018 AMY basis as the load and solar data.

Technology: NREL ATB 2024 T1 land-based wind configuration (6 MW, 170 m rotor,
115 m hub height). No pre-built power curve exists for this projected 2030 turbine,
so the curve is generated via SAM's built-in calculate_powercurve() from the ATB T1
physical specs plus standard parameters for a modern 3-stage geared turbine.

Citation: NREL Annual Technology Baseline 2024, Land-Based Wind.
https://atb.nrel.gov/electricity/2024/land-based_wind

BC-HRRR data is at 100 m hub height; SAM applies a power-law wind shear correction
(Hellmann exponent 0.14, flat terrain) over the 15 m gap to 115 m hub height.

Output is normalized AC capacity factor (kWh generated per kW rated per hour).
Multiply by installed MW to obtain absolute generation in MWh.

One column per input met file (5 total: East x3, North x1, South x1).
East zone points may be averaged into a single zone CF in a subsequent step.

Input:  data_cleaning/solar_wind_shapes/raw/wind/{name}.csv
Output: data_cleaning/solar_wind_shapes/wind_cf_profiles.csv
"""

PROJECT_ROOT = find_project_root()
RAW_WIND_DIR = PROJECT_ROOT / "data_cleaning" / "solar_wind_shapes" / "raw" / "wind"
OUTPUT_DIR   = PROJECT_ROOT / "data_cleaning" / "solar_wind_shapes"
OUTPUT_PATH  = OUTPUT_DIR / "wind_cf_profiles.csv"

WIND_FILES = [
    "East_2018_wind_point1",
    "East_2018_wind_point2",
    "East_2018_wind_point3",
    "North_2018_wind_point1",
    "South_2018_wind_point1",
]


def main():
    print("Generating ATB 2024 T1 power curve via SAM calculate_powercurve()...")
    curve_speeds, curve_power = build_power_curve()
    print(f"  Curve: {len(curve_speeds)} points, "
          f"rated at {max(curve_power):.0f} kW, "
          f"cut-in ~{next(s for s, p in zip(curve_speeds, curve_power) if p > 0):.2f} m/s")

    results = {}
    datetime_index = None

    print("\nRunning SAM Windpower for each met file...")
    for name in WIND_FILES:
        path = RAW_WIND_DIR / f"{name}.csv"
        print(f"  {name}...", end=" ", flush=True)
        resource, df = parse_bchrrr(path)
        cf = run_windpower(resource, curve_speeds, curve_power)
        results[f"{name}_cf"] = cf
        if datetime_index is None:
            datetime_index = build_datetime_index(df)
        annual_cf = sum(cf) / len(cf)
        print(f"annual CF = {annual_cf:.4f}  ({annual_cf * 8760:.0f} kWh/kW/yr)")

    output = pd.DataFrame(results, index=datetime_index)
    output.index.name = "datetime"
    output.to_csv(OUTPUT_PATH)
    print(f"\nSaved {len(output)} rows x {len(output.columns)} files -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
