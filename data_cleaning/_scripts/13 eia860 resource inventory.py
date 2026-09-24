"""
Script 13: EIA Form 860 (2024) — Colorado Generator Inventory

Downloads the EIA-860 2024 zip, reads Plant + Generator + Energy Storage
workbooks, filters to the PSCo/WACM footprint, assigns each generator to one
of the 6 model zones via spatial join, and writes a flat inventory CSV.

Writes:
  data_cleaning/resources/eia860/raw/eia860_2024.zip
  data_cleaning/resources/eia860/colorado_generators.csv

Prints:
  Zone x TechType summary table
  EnCompass input checklist (what is ready vs. still missing)

EIA-860 workbooks used:
  2___Plant_Y2024       lat/lon, county, BA code
  3_1_Generator_Y2024   capacity, prime mover, fuel, status, dates
                        (Operable + Proposed tabs)
  3_4_Energy_Storage_Y2024  MWh capacity, charge/discharge rates
                             (left-joined; NaN for non-storage units)
Deferred to later scripts:
  3_2_Wind, 3_3_Solar, 3_5_MultiFuel

commission_date for proposed units (fixed 2026-07-16):
  The Operable and Proposed tabs have different schemas. Operable uses
  "Operating Month"/"Operating Year" (-> op_month/op_year). Proposed has no
  "Planned Online Month/Year" field at all -- its actual expected in-service
  date is reported as "Current Month"/"Current Year". build_dates() falls back
  to op_month/op_year first, then this field, so commission_date is now
  populated for proposed units instead of silently staying blank.
"""

import argparse
import os
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from urllib import error as urllib_error
from urllib import request

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"
COUNTIES_SHP  = DATA_CLEANING / "counties" / "tl_2025_us_county.shp"
RAW_DIR       = DATA_CLEANING / "resources" / "eia860" / "raw"
OUT_DIR       = DATA_CLEANING / "resources" / "eia860"
OUT_CSV       = OUT_DIR / "colorado_generators.csv"

EIA860_YEAR     = 2024
EIA860_URL      = f"https://www.eia.gov/electricity/data/eia860/xls/eia860{EIA860_YEAR}.zip"
TARGET_BA_CODES = {"PSCO", "WACM"}
TARGET_STATUSES = {"OP", "SB", "P", "L", "T", "TS"}

# ---------------------------------------------------------------------------
# Zone mapping (copied from data_cleaning/_scripts/1 zone_map.py)
# ---------------------------------------------------------------------------
ZONE_MAPPING = {
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
COUNTY_TO_ZONE = {c: z for z, cs in ZONE_MAPPING.items() for c in cs}

# ---------------------------------------------------------------------------
# Technology map: (prime_mover, energy_source_1) -> EnCompass TechType
# ---------------------------------------------------------------------------
TECH_MAP = {
    ("CA", "NG"): "Gas:CC",   ("CS", "NG"): "Gas:CC",
    ("CT", "NG"): "Gas:CT",   ("GT", "NG"): "Gas:CT",
    ("ST", "NG"): "Gas:ST",
    ("IC", "NG"): "Gas:IC",   ("IC", "DFO"): "Gas:IC",
    ("ST", "BIT"): "Coal",    ("ST", "SUB"): "Coal",    ("ST", "RC"): "Coal",
    ("ST", "NUC"): "Nuclear",
    ("WT", "WND"): "Wind",    ("WS", "WND"): "Wind",
    ("PV", "SUN"): "Solar:PV", ("CP", "SUN"): "Solar:CSP", ("FL", "SUN"): "Solar:PV",
    ("HY", "WAT"): "Hydro",   ("PS", "WAT"): "Hydro:Pumped",
    ("BA", "MWH"): "Storage:Battery",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    cols = []
    for c in df.columns:
        c = str(c).strip().lower()
        c = re.sub(r"[\s/\-]+", "_", c)
        c = re.sub(r"[^a-z0-9_]", "", c)
        c = re.sub(r"_+", "_", c).strip("_")
        cols.append(c)
    df.columns = cols
    return df


def _fuzzy_find(namelist: list, *substrings: str) -> str | None:
    lower_subs = [s.lower() for s in substrings]
    for name in namelist:
        n = name.lower()
        if all(s in n for s in lower_subs):
            return name
    return None


def _read_xls_from_zip(zf: zipfile.ZipFile, filename: str,
                        sheet: str | int = 0) -> pd.DataFrame:
    with zf.open(filename) as f:
        return pd.read_excel(BytesIO(f.read()), sheet_name=sheet, header=1)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_eia860(force: bool = False) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"eia860_{EIA860_YEAR}.zip"
    if dest.exists() and not force:
        print(f"  Cached: {dest}")
        return dest
    print(f"  Downloading {EIA860_URL} ...")
    try:
        with request.urlopen(EIA860_URL, timeout=120) as resp:
            data = resp.read()
    except urllib_error.HTTPError as e:
        print(f"\nERROR: Failed to download EIA-860 {EIA860_YEAR}.")
        print(f"  URL:  {EIA860_URL}")
        print(f"  HTTP {e.code}: {e.reason}")
        raise SystemExit(1)
    except urllib_error.URLError as e:
        print(f"\nERROR: Network error downloading EIA-860 {EIA860_YEAR}.")
        print(f"  URL:  {EIA860_URL}")
        print(f"  {e.reason}")
        raise SystemExit(1)
    dest.write_bytes(data)
    print(f"  {len(data) / 1e6:.1f} MB -> {dest}")
    return dest


# ---------------------------------------------------------------------------
# Read workbooks
# ---------------------------------------------------------------------------

def read_plant_data(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        fname = _fuzzy_find(zf.namelist(), "plant_y")
        if not fname:
            raise FileNotFoundError(f"No Plant_Y workbook in zip. Files: {zf.namelist()}")
        df = _read_xls_from_zip(zf, fname)
    df = _normalize_cols(df)
    df = df.rename(columns={
        "plant_code":               "plant_code",
        "plant_name":               "plant_name",
        "state":                    "state",
        "county":                   "county",
        "latitude":                 "latitude",
        "longitude":                "longitude",
        "balancing_authority_code": "ba_code",
    })
    keep = [c for c in ["plant_code", "plant_name", "state", "county",
                         "latitude", "longitude", "ba_code"] if c in df.columns]
    df = df[keep].copy()
    df["plant_code"] = pd.to_numeric(df["plant_code"], errors="coerce")
    df = df.dropna(subset=["plant_code"])
    df["plant_code"] = df["plant_code"].astype(int)
    df["latitude"]   = pd.to_numeric(df["latitude"],  errors="coerce")
    df["longitude"]  = pd.to_numeric(df["longitude"], errors="coerce")
    print(f"  {len(df)} plant records")
    return df


def read_generator_data(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        fname = _fuzzy_find(zf.namelist(), "3_1", "generator_y")
        if not fname:
            raise FileNotFoundError("No 3_1_Generator_Y workbook in zip.")
        chunks = []
        for tab in ["Operable", "Proposed"]:
            try:
                df = _read_xls_from_zip(zf, fname, sheet=tab)
                df = _normalize_cols(df)
                df["status_tab"] = tab.lower()
                chunks.append(df)
                print(f"    {tab}: {len(df)} rows")
            except Exception as exc:
                print(f"    {tab}: skipped ({exc})")

    gen = pd.concat(chunks, ignore_index=True)
    gen = gen.rename(columns={
        "plant_code":               "plant_code",
        "generator_id":             "generator_id",
        "technology":               "technology",
        "prime_mover":              "prime_mover",
        "energy_source_1":          "energy_source",
        "nameplate_capacity_mw":    "nameplate_mw",
        "summer_capacity_mw":       "summer_mw",
        "status":                   "status",
        "operating_month":          "op_month",
        "operating_year":           "op_year",
        "planned_retirement_month": "ret_month",
        "planned_retirement_year":  "ret_year",
        "current_month":            "planned_online_month",
        "current_year":             "planned_online_year",
        "balancing_authority_code": "ba_code_gen",
        "state":                    "state_gen",
    })
    keep = [c for c in ["plant_code", "generator_id", "technology", "prime_mover",
                         "energy_source", "nameplate_mw", "summer_mw", "status",
                         "op_month", "op_year", "ret_month", "ret_year",
                         "planned_online_month", "planned_online_year",
                         "ba_code_gen", "state_gen", "status_tab"] if c in gen.columns]
    gen = gen[keep].copy()
    gen["plant_code"]   = pd.to_numeric(gen["plant_code"], errors="coerce")
    gen = gen.dropna(subset=["plant_code"])
    gen["plant_code"]   = gen["plant_code"].astype(int)
    gen["nameplate_mw"] = pd.to_numeric(gen["nameplate_mw"], errors="coerce")
    gen["summer_mw"]    = pd.to_numeric(gen["summer_mw"],    errors="coerce")
    print(f"  {len(gen)} generator records (Operable + Proposed)")
    return gen


def read_storage_data(zip_path: Path) -> pd.DataFrame:
    _empty = pd.DataFrame(columns=["plant_code", "generator_id",
                                    "storage_mwh", "max_charge_mw", "max_discharge_mw"])
    with zipfile.ZipFile(zip_path) as zf:
        fname = _fuzzy_find(zf.namelist(), "3_4", "energy_storage")
        if not fname:
            print("  WARNING: No 3_4_Energy_Storage workbook found; storage columns will be NaN.")
            return _empty
        chunks = []
        for tab in ["Operable", "Proposed"]:
            try:
                df = _read_xls_from_zip(zf, fname, sheet=tab)
                df = _normalize_cols(df)
                chunks.append(df)
                print(f"    {tab}: {len(df)} rows")
            except Exception:
                pass

    if not chunks:
        return _empty
    stor = pd.concat(chunks, ignore_index=True)
    stor = stor.rename(columns={
        "plant_code":                    "plant_code",
        "generator_id":                  "generator_id",
        "nameplate_energy_capacity_mwh": "storage_mwh",
        "maximum_charge_rate_mw":        "max_charge_mw",
        "maximum_discharge_rate_mw":     "max_discharge_mw",
    })
    keep = [c for c in ["plant_code", "generator_id", "storage_mwh",
                         "max_charge_mw", "max_discharge_mw"] if c in stor.columns]
    stor = stor[keep].copy()
    stor["plant_code"] = pd.to_numeric(stor["plant_code"], errors="coerce")
    stor = stor.dropna(subset=["plant_code"])
    stor["plant_code"] = stor["plant_code"].astype(int)
    for col in ["storage_mwh", "max_charge_mw", "max_discharge_mw"]:
        if col in stor.columns:
            stor[col] = pd.to_numeric(stor[col], errors="coerce")
        else:
            stor[col] = float("nan")
    stor = stor.drop_duplicates(subset=["plant_code", "generator_id"], keep="first")
    print(f"  {len(stor)} storage records")
    return stor


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def filter_footprint(gen_df: pd.DataFrame, plant_df: pd.DataFrame,
                     storage_df: pd.DataFrame) -> pd.DataFrame:
    df = gen_df.merge(plant_df, on="plant_code", how="left")

    # Prefer plant-level ba_code / state; fill from generator-level where missing
    if "ba_code" not in df.columns and "ba_code_gen" in df.columns:
        df = df.rename(columns={"ba_code_gen": "ba_code"})
    elif "ba_code_gen" in df.columns:
        df["ba_code"] = df["ba_code"].fillna(df["ba_code_gen"])

    if "state" not in df.columns and "state_gen" in df.columns:
        df = df.rename(columns={"state_gen": "state"})
    elif "state_gen" in df.columns:
        df["state"] = df["state"].fillna(df["state_gen"])

    # Join storage sub-table
    df = df.merge(storage_df, on=["plant_code", "generator_id"], how="left")
    for col in ["storage_mwh", "max_charge_mw", "max_discharge_mw"]:
        if col not in df.columns:
            df[col] = float("nan")

    # Status filter
    df = df[df["status"].isin(TARGET_STATUSES)].copy()

    # State filter: Colorado plants only (out-of-state WACM plants excluded)
    state_mask = df["state"].fillna("").str.strip().str.upper() == "CO"
    df = df[state_mask].copy()

    # Tag whether plant is also in PSCo/WACM BA (informational)
    ba_mask = df["ba_code"].fillna("").str.strip().str.upper().isin(TARGET_BA_CODES)
    df["filter_source"] = ba_mask.map({True: "CO+BA", False: "CO_only"})

    print(f"  {len(df)} generators after filter")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Zone assignment
# ---------------------------------------------------------------------------

def build_zone_polygons() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(COUNTIES_SHP)
    co  = gdf[gdf["STATEFP"] == "08"].copy()
    co["ZONE"] = co["NAME"].map(COUNTY_TO_ZONE)
    unmapped = co[co["ZONE"].isna()]
    if len(unmapped):
        print(f"  WARNING: {len(unmapped)} CO counties not in ZONE_MAPPING: {unmapped['NAME'].tolist()}")
    zones = co.dissolve(by="ZONE")
    if "4326" not in str(zones.crs):
        zones = zones.to_crs("EPSG:4326")
    return zones


def assign_zones(df: pd.DataFrame, zones_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    df = df.copy()
    df["zone_assignment"] = None

    # Stage 1: point-in-polygon spatial join for rows with valid coordinates
    has_coords = df["latitude"].notna() & df["longitude"].notna()
    if has_coords.any():
        valid_idx = df.index[has_coords]
        geom      = [Point(lo, la) for lo, la in
                     zip(df.loc[has_coords, "longitude"], df.loc[has_coords, "latitude"])]
        pts_gdf   = gpd.GeoDataFrame({"orig_idx": valid_idx}, geometry=geom, crs="EPSG:4326")
        pts_gdf   = pts_gdf.reset_index(drop=True)

        zones_right = zones_gdf.reset_index()[["ZONE", "geometry"]]
        joined  = gpd.sjoin(pts_gdf, zones_right, how="left", predicate="within")
        joined  = joined[~joined.index.duplicated(keep="first")]
        zone_map = joined.set_index("orig_idx")["ZONE"]
        df.loc[has_coords, "zone_assignment"] = df.index[has_coords].map(zone_map)

    # Stage 2: county-name fallback for unresolved rows
    needs_fallback = df["zone_assignment"].isna()
    if needs_fallback.any():
        def _county_lookup(val):
            if pd.isna(val): return None
            name = str(val).strip().title()
            if name in COUNTY_TO_ZONE: return COUNTY_TO_ZONE[name]
            for k in COUNTY_TO_ZONE:
                if k.lower() in name.lower(): return COUNTY_TO_ZONE[k]
            return None
        df.loc[needs_fallback, "zone_assignment"] = (
            df.loc[needs_fallback, "county"].map(_county_lookup)
        )

    # Stage 3: flag anything still unresolved
    df.loc[df["zone_assignment"].isna(), "zone_assignment"] = "MANUAL_REVIEW"
    manual = (df["zone_assignment"] == "MANUAL_REVIEW").sum()
    print(f"  {manual} generators flagged MANUAL_REVIEW (likely out-of-state)")
    return df


# ---------------------------------------------------------------------------
# Derived columns
# ---------------------------------------------------------------------------

def build_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def _series(col):
        return (pd.to_numeric(df[col], errors="coerce") if col in df.columns
                else pd.Series([float("nan")] * len(df), index=df.index))

    def _date_col(months, years):
        result = []
        for m, y in zip(months, years):
            if pd.isna(m) or pd.isna(y):
                result.append(None)
            else:
                result.append(f"{int(y):04d}-{int(m):02d}-01")
        return result

    op_dates      = _date_col(_series("op_month"),             _series("op_year"))
    planned_dates = _date_col(_series("planned_online_month"), _series("planned_online_year"))
    # Use actual operating date first; fall back to planned online date for proposed units
    df["commission_date"] = [a if a is not None else b
                              for a, b in zip(op_dates, planned_dates)]
    df["retirement_date"] = _date_col(_series("ret_month"), _series("ret_year"))
    return df


def build_tech_type(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["tech_type"] = df.apply(
        lambda r: TECH_MAP.get(
            (str(r.get("prime_mover", "") or "").strip(),
             str(r.get("energy_source", "") or "").strip()),
            "Other"
        ),
        axis=1,
    )
    return df


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def apply_manual_overrides(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply known corrections to EIA-860 data that lags real-world plant changes.
    Each entry documents plant_code, generator_id, what changed, and why.
    """
    df = df.copy()

    # Pawnee (6248-1): converted from coal to natural gas steam.
    # EIA-860 2024 still shows SUB coal; actual fuel switch occurred ~2024-2025.
    mask = (df["plant_code"] == 6248) & (df["generator_id"] == "1")
    if mask.sum() == 0:
        print("  WARNING: Pawnee (6248-1) not found — skipping override.")
    else:
        df.loc[mask, "energy_source"] = "NG"
        df.loc[mask, "technology"]    = "Conventional Steam Natural Gas"
        df.loc[mask, "tech_type"]     = "Gas:ST"
        print(f"  Override: Pawnee (6248-1) Coal -> Gas:ST (fuel switch, EIA lag)")

    return df


def assemble_output(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "plant_code", "generator_id", "plant_name",
        "technology", "prime_mover", "energy_source", "tech_type",
        "nameplate_mw", "summer_mw",
        "storage_mwh", "max_charge_mw", "max_discharge_mw",
        "status", "commission_date", "retirement_date",
        "ba_code", "state", "county",
        "latitude", "longitude", "zone_assignment", "filter_source",
    ]
    return df[[c for c in cols if c in df.columns]].copy()


def print_summary(df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("GENERATOR INVENTORY SUMMARY")
    print("=" * 72)
    print(f"\nTotal generators: {len(df)}")

    print("\nFilter source:")
    for src, cnt in df["filter_source"].value_counts().items():
        print(f"  {src:<8}: {cnt:4d}")

    print("\nZone x TechType  (n = count, mw = summer MW):")
    pivot = df.groupby(["zone_assignment", "tech_type"]).agg(
        n=("generator_id", "count"),
        mw=("summer_mw", "sum"),
    )
    print(pivot.to_string())

    no_coords = df["latitude"].isna().sum()
    manual    = (df["zone_assignment"] == "MANUAL_REVIEW").sum()
    no_summer = df["summer_mw"].isna().sum()
    print(f"\nData quality:")
    print(f"  Missing lat/lon:       {no_coords}")
    print(f"  Zone = MANUAL_REVIEW:  {manual}")
    print(f"  Missing summer_mw:     {no_summer}  (expected for Proposed units)")

    other = df[df["tech_type"] == "Other"][["prime_mover", "energy_source"]].value_counts()
    if len(other):
        print(f"\nUnmapped tech types (extend TECH_MAP as needed):")
        print(other.to_string())


def print_encompass_checklist(df: pd.DataFrame) -> None:
    stor_ready = df["storage_mwh"].notna().sum()
    print("\n" + "=" * 72)
    print("EnCompass RESOURCE INPUT CHECKLIST")
    print("=" * 72)
    W = [26, 22, 28]
    rows = [
        ("Input",                    "Status",                         "Next Source"),
        ("-" * W[0],                 "-" * W[1],                       "-" * W[2]),
        ("Name",                     "READY",                          "plant_name + generator_id"),
        ("Area",                     "READY",                          "zone_assignment"),
        ("TechType",                 "READY",                          "prime_mover + energy_source"),
        ("EIACode",                  "READY",                          "plant_code"),
        ("MaxCap (MW)",              "READY",                          "summer_mw (nameplate fallback)"),
        ("Fuel",                     "READY",                          "energy_source"),
        ("CommissionDate",           "PARTIAL",                        "NaN for some Proposed units"),
        ("RetirementDate",           "PARTIAL",                        "NaN where not yet planned"),
        ("storage_mwh",              f"READY ({stor_ready} units)",    "3_4_Energy_Storage"),
        ("max_charge/discharge_mw",  f"READY ({stor_ready} units)",    "3_4_Energy_Storage"),
        ("Units",                    "DEFERRED",                       "grouping logic -> Script 14"),
        ("AvgHtRate",                "MISSING",                        "-> EIA-923 / EPA CAMPD"),
        ("MinCap",                   "MISSING",                        "-> technology assumptions"),
        ("FOR",                      "MISSING",                        "-> NERC GADS class averages"),
        ("EnCost (VOM $/MWh)",       "MISSING",                        "-> EIA Electric Power Annual"),
        ("FixedRate (FOM $/kW-yr)",  "MISSING",                        "-> EIA Electric Power Annual"),
        ("FirmCap (%)",              "MISSING",                        "-> technology assumptions"),
        ("NetGenLim (CF shape)",     "DONE",                           "encompass script 3: 4_Renewable_CF_Shapes"),
    ]
    for label, status, note in rows:
        print(f"  {label:<{W[0]}} {status:<{W[1]}} {note}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Build the EIA-860 Colorado generator inventory.")
    parser.add_argument(
        "--redownload", action="store_true",
        help="Force a fresh EIA-860 download even if a cached copy already exists.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/7] Downloading EIA-860...")
    zip_path = download_eia860(force=args.redownload)

    print("\n[2/7] Reading plant data...")
    plant_df = read_plant_data(zip_path)

    print("\n[3/7] Reading generator data (Operable + Proposed tabs)...")
    gen_df = read_generator_data(zip_path)

    print("\n[4/7] Reading energy storage data...")
    storage_df = read_storage_data(zip_path)

    print("\n[5/7] Filtering to PSCo/WACM footprint...")
    df = filter_footprint(gen_df, plant_df, storage_df)

    print("\n[6/7] Assigning model zones + building derived columns...")
    zones_gdf = build_zone_polygons()
    df = assign_zones(df, zones_gdf)
    df = build_dates(df)
    df = build_tech_type(df)
    df = apply_manual_overrides(df)
    df = assemble_output(df)

    print(f"\n[7/7] Saving -> {OUT_CSV}")
    df.to_csv(OUT_CSV, index=False)
    print(f"  Wrote {len(df)} rows x {len(df.columns)} columns")

    print_summary(df)
    print_encompass_checklist(df)
    print(f"\nDone.")


if __name__ == "__main__":
    main()
