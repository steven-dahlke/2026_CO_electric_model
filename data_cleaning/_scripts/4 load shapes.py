import argparse
import os
import sys
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import s3fs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

parser = argparse.ArgumentParser(description="Build hourly load shapes from NREL ResStock/ComStock S3 data.")
parser.add_argument(
    "--redownload", action="store_true",
    help="Force a fresh S3 fetch even if the output file already exists.",
)
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = find_project_root()
DATA_LOAD = PROJECT_ROOT / "data_cleaning" / "load"
DATA_COUNTIES = PROJECT_ROOT / "data_cleaning" / "counties"
FINAL_OUTPUT = DATA_LOAD / "load_shapes_zone_sector_2018.csv"

if FINAL_OUTPUT.exists() and not args.redownload:
    print(f"[skip] {FINAL_OUTPUT.name} already exists. Use --redownload to force a fresh S3 fetch.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Zone → county mapping (mirrors Script 1)
# ---------------------------------------------------------------------------
zone_county_map = {
    "Denver":   ["Denver", "Arapahoe", "Jefferson", "Douglas", "Broomfield",
                 "Adams", "Boulder", "Gilpin", "Clear Creek"],
    "North":    ["Larimer", "Weld", "Morgan"],
    "South":    ["El Paso", "Pueblo", "Fremont", "Huerfano", "Las Animas",
                 "Alamosa", "Saguache", "Rio Grande", "Conejos", "Costilla",
                 "Mineral", "Custer", "Chaffee", "Park", "Teller"],
    "East":     ["Logan", "Washington", "Kit Carson", "Lincoln", "Yuma",
                 "Phillips", "Sedgwick", "Cheyenne", "Kiowa", "Crowley",
                 "Otero", "Bent", "Prowers", "Baca", "Elbert"],
    "Mountain": ["Summit", "Eagle", "Pitkin", "Grand", "Lake", "Jackson"],
    "West":     ["Mesa", "Montrose", "Delta", "Garfield", "Routt", "Moffat",
                 "Rio Blanco", "Gunnison", "La Plata", "Archuleta", "San Juan",
                 "Dolores", "Montezuma", "San Miguel", "Ouray", "Hinsdale"],
}

SECTORS = ["Residential", "Commercial"]

# ---------------------------------------------------------------------------
# Phase 1 — Load county energy weights from Script 1 output
# ---------------------------------------------------------------------------
print("Loading county energy weights...")
county_weights = pd.read_csv(DATA_LOAD / "county_total_energy_CO.csv")
# Columns: county_name, Residential_MWh, Commercial_MWh, Industrial_MWh, Total_MWh
county_weights = county_weights.set_index("county_name")

# ---------------------------------------------------------------------------
# Phase 2 — Build county name → GISJOIN lookup via shapefile
# ---------------------------------------------------------------------------
print("Building county name → GISJOIN mapping from shapefile...")
counties_shp = gpd.read_file(DATA_COUNTIES / "tl_2025_us_county.shp")
co_counties = counties_shp[counties_shp["STATEFP"] == "08"][["NAME", "COUNTYFP"]].copy()
# GISJOIN format from NREL README: g + state_fips(2) + "0" + county_fips(3) + "0"
co_counties["gisjoin"] = "g08" + "0" + co_counties["COUNTYFP"] + "0"
name_to_gisjoin = co_counties.set_index("NAME")["gisjoin"].to_dict()

# Verify all mapped counties resolve to a GISJOIN
all_counties = [c for counties in zone_county_map.values() for c in counties]
missing_gisjoin = [c for c in all_counties if c not in name_to_gisjoin]
if missing_gisjoin:
    warnings.warn(f"No GISJOIN found for counties: {missing_gisjoin}")
else:
    print(f"  All {len(all_counties)} zone counties matched to GISJOIN identifiers.")

# ---------------------------------------------------------------------------
# Phase 3 — S3 file discovery
# ---------------------------------------------------------------------------
S3_BASE = "oedi-data-lake/nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021"
RES_PATH = f"{S3_BASE}/resstock_amy2018_release_1/timeseries_aggregates/by_county/state=CO"
COM_PATH = f"{S3_BASE}/comstock_amy2018_release_1/timeseries_aggregates/by_county/state=CO"
ELEC_COL = "out.electricity.total.energy_consumption"

print("Connecting to NREL OEDI S3 (anonymous)...")
fs = s3fs.S3FileSystem(anon=True)

def discover_county_files(s3_path):
    """Return dict mapping gisjoin → list of s3 file paths for that county."""
    all_files = fs.ls(s3_path)
    county_files = {}
    for f in all_files:
        fname = os.path.basename(f)          # e.g. g0800590-single-family_detached.csv
        if not fname.endswith(".csv"):
            continue
        gisjoin = fname.split("-")[0]        # e.g. g0800590
        county_files.setdefault(gisjoin, []).append(f)
    return county_files

print("Discovering ResStock CO files...")
res_files_by_gisjoin = discover_county_files(RES_PATH)
print(f"  Found {sum(len(v) for v in res_files_by_gisjoin.values())} ResStock files "
      f"across {len(res_files_by_gisjoin)} counties.")

print("Discovering ComStock CO files...")
com_files_by_gisjoin = discover_county_files(COM_PATH)
print(f"  Found {sum(len(v) for v in com_files_by_gisjoin.values())} ComStock files "
      f"across {len(com_files_by_gisjoin)} counties.")

sector_files = {
    "Residential": res_files_by_gisjoin,
    "Commercial":  com_files_by_gisjoin,
}

# ---------------------------------------------------------------------------
# Phase 4 — County-level profile extraction (15-min → hourly, EST → MST)
# ---------------------------------------------------------------------------
def read_county_profile(file_paths):
    """
    Read all building-type CSV files for one county, sum the electricity column,
    resample 15-min intervals to hourly, and return (series_8760, total_models_used).
    """
    frames = []
    total_models = 0
    for path in file_paths:
        with fs.open(path, "rb") as fh:
            df = pd.read_csv(fh, usecols=["timestamp", "models_used", ELEC_COL],
                             parse_dates=["timestamp"])
        total_models += int(df["models_used"].iloc[0])
        frames.append(df[["timestamp", ELEC_COL]].set_index("timestamp"))

    combined = pd.concat(frames).groupby(level=0).sum()        # sum building types
    hourly = combined.resample("h").sum()[ELEC_COL].iloc[:8760]  # 15-min  hourly, trim to 8760

    # No timezone shift needed; NREL EULP data is already in local time (with DST)
    hourly_local = pd.Series(hourly.values, name=path)

    return hourly_local, total_models

# Build {sector: {county_name: series_8760}}
print("\nExtracting county profiles from S3 (this may take several minutes)...")
county_profiles = {s: {} for s in SECTORS}
models_log = []

for sector in SECTORS:
    files_by_gisjoin = sector_files[sector]
    weight_col = "Residential_MWh" if sector == "Residential" else "Commercial_MWh"

    for zone, counties in zone_county_map.items():
        for county in counties:
            gisjoin = name_to_gisjoin.get(county)
            if gisjoin is None:
                continue
            county_file_list = files_by_gisjoin.get(gisjoin)
            if not county_file_list:
                print(f"  [WARNING] No NREL {sector} files found for {county} ({gisjoin}) — skipping.")
                continue

            series, n_models = read_county_profile(county_file_list)
            county_profiles[sector][county] = series
            models_log.append({
                "sector": sector, "zone": zone, "county": county,
                "gisjoin": gisjoin, "building_type_files": len(county_file_list),
                "models_used": n_models,
            })
            print(f"  {sector:12s} | {zone:8s} | {county:20s} | "
                  f"{len(county_file_list):3d} files | {n_models:5d} models")

# Print models-used summary for auditability
models_df = pd.DataFrame(models_log)
print("\n--- Models-used summary by county ---")
print(models_df[["sector", "zone", "county", "models_used"]].to_string(index=False))

# ---------------------------------------------------------------------------
# Phase 5 — Zone-level weighted aggregation → normalized shapes
# ---------------------------------------------------------------------------
print("\nAggregating county profiles to zone shapes...")

def weighted_normalized_shape(counties_in_zone, profiles_dict, weights_series, weight_col):
    """
    Weighted average of normalized county load shapes.
    weight_col: column name in county_weights (e.g. 'Residential_MWh')
    """
    weighted_sum = None
    total_weight = 0.0

    for county in counties_in_zone:
        if county not in profiles_dict:
            continue  # No NREL data; excluded
        profile = profiles_dict[county]
        if profile.sum() == 0:
            continue

        # Energy weight from Script 1 actuals
        if county not in weights_series.index:
            warnings.warn(f"No energy weight for {county}; skipping in zone aggregation.")
            continue
        w = float(weights_series.loc[county, weight_col])
        if w <= 0:
            continue

        norm_shape = profile / profile.sum()   # normalize to fraction
        if weighted_sum is None:
            weighted_sum = w * norm_shape.values
        else:
            weighted_sum += w * norm_shape.values
        total_weight += w

    if weighted_sum is None or total_weight == 0:
        raise ValueError("No valid county profiles for zone.")

    zone_shape = weighted_sum / total_weight   # weighted average of normalized shapes
    # Renormalize to exactly 1.0 (guards against floating-point drift)
    zone_shape = zone_shape / zone_shape.sum()
    return zone_shape

output_cols = {}
for sector in SECTORS:
    weight_col = "Residential_MWh" if sector == "Residential" else "Commercial_MWh"
    for zone in zone_county_map:
        col_name = f"{zone}_{sector[:3]}"   # e.g. "Denver_Res", "Denver_Com"
        shape = weighted_normalized_shape(
            counties_in_zone=zone_county_map[zone],
            profiles_dict=county_profiles[sector],
            weights_series=county_weights,
            weight_col=weight_col,
        )
        output_cols[col_name] = shape
        print(f"  Built shape: {col_name}  (sum={shape.sum():.6f})")

# ---------------------------------------------------------------------------
# Phase 6 — Output
# ---------------------------------------------------------------------------
shapes_df = pd.DataFrame(output_cols)
# Add an hour index (1–8760) for readability
shapes_df.index = pd.RangeIndex(start=1, stop=8761, step=1)
shapes_df.index.name = "hour"

output_path = FINAL_OUTPUT
shapes_df.to_csv(output_path)
print(f"\nSaved load shapes to {output_path}")
print(f"Shape: {shapes_df.shape}  (rows=hours, cols=zone-sector)")

# Quick sanity check — all columns should sum to ~1.0
col_sums = shapes_df.sum()
print("\nColumn sums (should all be 1.0):")
print(col_sums.to_string())

