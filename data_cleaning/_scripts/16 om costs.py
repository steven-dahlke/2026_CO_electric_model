"""
Script 16: O&M Costs

Enriches colorado_resources.csv (Scripts 14-15 output) with fixed and variable O&M costs.
New columns: FixedRate ($/kW-yr), EnCost ($/MWh), om_source.

Sub-plan A — ATB lookup table
  Build atb_om_lookup.csv from ATB 2024 Moderate scenario. Provides fixed_om, variable_om,
  and fixed_share ratio by TechType. Used for fallback values and fixed/variable split ratios.
  Source: NREL ATB 2024, Moderate scenario
  URL: https://oedi-data-lake.s3.amazonaws.com/ATB/electricity/csv/2024/v3.0.0/ATBe.csv

Sub-plan B1 — Form 1 (Schedule 402) for named CO thermal plants
  25 resources assigned from FERC Form 1 Schedule 402, 3-yr avg 2021-2023 non-fuel O&M.
  Source: PUDL core_ferc1__yearly_steam_plants_sched402.csv (local download)
  Output: costs/form1/form1_co_om.csv
  Split: non_fuel_om_kw from Form 1; fixed/variable split via ATB fixed_share at actual CF.
  Utilities covered: PSCo (227), PacifiCorp (303), Comanche co-owners (40, 205), Tri-State (353).

Sub-plan B2 — Hydro O&M
  15 resources assigned using two sources:
  - Cabin Creek (PSH, PSCo): Form 1 Schedule 408 (PUDL S3), 2024-2025 post-upgrade years.
    Source: PUDL core_ferc1__yearly_pumped_storage_plants_sched408.parquet
    Output: costs/form1/form1_co_hydro_om.csv
  - Remaining hydro (conventional + federal PSH): ORNL empirical medians by size class.
    Source: Oladosu & Sasthav (2022), ORNL/TM-2021/2297, DOI: 10.2172/1845786
    Inflated to 2025$ via CPI-U ×1.237 (2020 avg 258.8 → 2025 est. 320.4).

Sub-plan C — Wind, Solar:PV, Storage:Battery O&M
  45 resources assigned using three sources in a documented hierarchy:

  Wind (10 resources): per-EIA-plant rate table → capacity-weighted average per resource group.
    - Form 1 Schedule 410 (PUDL S3) for 4 utility-owned CO wind plants:
        Rush Creek (60619, PSCo), Cheyenne Ridge (62952, PSCo),
        Peak View (60143, Black Hills CO), Busch Ranch (57980, Black Hills CO, 2021-2022 only).
      All other CO wind plants are PURPA QFs / IPPs and do not file Form 1.
      Source: PUDL core_ferc1__yearly_small_plants_sched410.parquet
    - LBNL vintage-based medians for remaining 29 plants:
        pre-2010: $20/kW | 2010-2019: $21/kW | 2020+: $18/kW
      Source: LBNL Land-Based Wind Market Report 2024 Ed. (LBNL-2001724), pp.47-48
    - Groups with mixed Form 1 + LBNL plants: om_source = 'form1_lbnl_blend_2024'
    Output: costs/form1/form1_co_wind_om.csv (all 33 CO wind plants, source-labeled)

  Solar:PV (25 resources): LBNL Utility-Scale Solar 2024 Ed. (LBNL-2001700), p.25
    - operating (12 grouped existing resources): $22/kWac-yr, all-ages fleet median
    - proposed (13 named projects): $11/kWac-yr, newest cohort (2023 obs.)
    VOM = 0 for all solar. om_source = 'lbnl_solar_2024'

  Storage:Battery (10 resources): ATB 2024 Moderate, 4Hr Battery Storage.
    om_source = 'atb_2024'

Sub-plan D — Remaining thermal O&M
  D1 Pueblo Airport CC (plant 56998, Black Hills CO Electric utility 309): Form 1 Schedule 402
  'Units 1 & 2' rows (200 MW NGCC steam portion), 3-yr avg 2021-2023.
  'Unit 6' (42 MW) and the GT units at the same EIA plant code are excluded from this match;
  GT units (Gas:CT) are not covered by Schedule 402 and receive ATB below.
  D2 Coal peer proxy — existing Coal resources without Form 1 coverage (Rawhide/PRPA, Ray Nixon/CSU)
  use a capacity-weighted average of the three CO Form 1 coal peers (Comanche 470, Hayden 525,
  Craig 6021). ATB Coal-new ($85.70/kW) is a new-build planning cost inappropriate for existing
  plants; Form 1 peers yield ~$43.6/kW-yr total, split to ~$30/kW fixed and ~$3.3/MWh VOM.
  om_source = 'form1_co_coal_peer_proxy'. Proposed Coal resources receive ATB in D3.
  D3 All other remaining thermal resources assigned ATB 2024 Moderate by TechType:
    Gas:CC, Gas:CT: direct ATB lookup.
    Gas:ST, Gas:IC: Combustion Turbine proxy (no dedicated ATB equivalent).
    Proposed Gas:CT (canyon_peak, horizon, rawhide_proposed): ATB new-build values are
    appropriate since no actual cost history exists.

ATB 2024 tech structure notes (verified 2026-06-19):
  - Natural gas CC and CT are under technology="NaturalGas_FE"; techdetail distinguishes type
  - Wind, Solar:PV, Storage:Battery have Fixed O&M only; Variable O&M = 0 in ATB
  - Nuclear data starts at year 2030; earlier years use 2030 value as proxy
  - Coal uses techdetail="Coal-new" (excludes CCS variants)
  - Battery uses techdetail="4Hr Battery Storage" (standard utility-scale duration)
"""

import argparse
import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT  = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"
RESOURCES_CSV = DATA_CLEANING / "resources" / "colorado_resources.csv"

ATB_CACHE    = DATA_CLEANING / "resources" / "costs" / "atb" / "raw" / "atb_2024.csv"
ATB_OUT      = DATA_CLEANING / "resources" / "costs" / "atb" / "atb_om_lookup.csv"
ATB_URL      = "https://oedi-data-lake.s3.amazonaws.com/ATB/electricity/csv/2024/v3.0.0/ATBe.csv"
ATB_YEAR     = 2024          # base year; used for existing resource fixed/variable ratio
ATB_SCENARIO = "moderate"    # ATB CSV uses Title Case but we lowercase in load_atb_raw
ATB_YEARS    = list(range(2024, 2036))  # years extracted for proposed vintage matching

# Set False after first run confirms tech labels are correct
PRINT_ATB_TECHS = False

# Tech specs: how to extract O&M for each of our TechType labels from ATB 2024.
# Keys:
#   atb_tech         : ATB "technology" column value
#   detail_contains  : keep techdetail rows containing this string (case-insensitive)
#   detail_exact     : keep only this exact techdetail value
#   detail_excludes  : drop techdetail rows containing this string (applied after contains)
#   vom_default      : use this VOM when ATB has no Variable O&M row (e.g. wind = 0)
#   year_fallback    : if target year has no data, use nearest available year
ATB_TECH_SPEC: dict[str, dict] = {
    "Coal": {
        "atb_tech":       "Coal_FE",
        "detail_exact":   "Coal-new",          # excludes CCS variants
    },
    "Gas:CC": {
        "atb_tech":       "NaturalGas_FE",
        "detail_contains": "Combined Cycle",   # all frame configs, averaged
        "detail_excludes": "CCS",
    },
    "Gas:CT": {
        "atb_tech":       "NaturalGas_FE",
        "detail_contains": "Combustion Turbine",
    },
    "Gas:ST": {
        "atb_tech":       "NaturalGas_FE",     # no ATB equivalent; proxy via CT
        "detail_contains": "Combustion Turbine",
    },
    "Gas:IC": {
        "atb_tech":       "NaturalGas_FE",     # no ATB equivalent; proxy via CT
        "detail_contains": "Combustion Turbine",
    },
    "Nuclear": {
        "atb_tech":       "Nuclear",
        "detail_contains": "Large",            # "Nuclear - Large"; data starts 2030
    },
    "Storage:Battery": {
        "atb_tech":       "Utility-Scale Battery Storage",
        "detail_exact":   "4Hr Battery Storage",
        "vom_default":    0.0,                 # ATB reports no VOM for battery
    },
    "Solar:PV": {
        "atb_tech":       "UtilityPV",
        "vom_default":    0.0,                 # ATB reports no VOM for solar
    },
    "Wind": {
        "atb_tech":       "LandbasedWind",
        "vom_default":    0.0,                 # ATB reports no VOM for wind
    },
    "Hydro": {
        "atb_tech":       "Hydropower",
        "detail_contains": "NPD1",             # non-powered dam variant; all hydro variants have VOM=0
        "vom_default":    0.0,
    },
    "Hydro:Pumped": {
        "atb_tech":       "Pumped Storage Hydropower",
        "detail_contains": "NatlClass1",       # all NatlClass variants identical (Fixed=$20.15, VOM=$0.58)
    },
}

# Reference capacity factors for computing fixed_share = fixed_om / (fixed_om + vom*8760*CF/1000)
# Used in Sub-plan B to split FERC Form 1 total O&M into FixedRate and EnCost.
REF_CF: dict[str, float] = {
    "Coal":            0.60,
    "Gas:CC":          0.50,
    "Gas:CT":          0.15,
    "Gas:ST":          0.20,
    "Gas:IC":          0.20,
    "Nuclear":         0.90,
    "Storage:Battery": 0.25,
    "Solar:PV":        0.25,
    "Wind":            0.35,
    "Hydro":           0.40,   # VOM=0 so this CF has no effect on fixed_share; included for completeness
    "Hydro:Pumped":    0.15,
}

ATB_PARAM_FIXED = "Fixed O&M"
ATB_PARAM_VOM   = "Variable O&M"


# ---------------------------------------------------------------------------
# Form 1 — Sub-plan B1 constants
# ---------------------------------------------------------------------------

FORM1_RAW_CSV = (
    DATA_CLEANING / "resources" / "costs" / "form1" / "raw"
    / "core_ferc1__yearly_steam_plants_sched402.csv"
)
FORM1_OUT         = DATA_CLEANING / "resources" / "costs" / "form1" / "form1_co_om.csv"
FORM1_CO_UTIL_IDS = [40, 205, 227, 303, 353]   # PSCo, PacifiCorp (Craig/Hayden), Comanche co-owners, Tri-State (Craig)
FORM1_YEARS       = [2021, 2022, 2023]

# (utility_id_ferc1, plant_id_eia) co-owner rows to drop before aggregation.
# Utility 205 files for Comanche (470) but has wildly inconsistent fuel cost
# reporting ($202/MWh in 2021 vs PSCo's $20/MWh for the same plant and year);
# PSCo (227) is the primary operator and the reliable source for Comanche O&M.
FORM1_EXCLUDE_PAIRS: set[tuple[int, int]] = {
    (205, 470),
}

# Per-plant year overrides: restrict to only these report_years before averaging.
# Falls back to FORM1_YEARS for any plant not listed here.
# Comanche (470): PSCo reports 1,635 MW in 2021-2022 (Unit 1 still in books);
# 2023 reflects the post-retirement fleet (Units 2+3 only, 1,252 MW). Using 2023
# avoids blending Unit 1 costs and capacity into the active-fleet rate.
FORM1_PLANT_YEARS: dict[int, list[int]] = {
    470: [2023],
}

# (utility_id_ferc1, lower(plant_name_ferc1)) → plant_id_eia
# Derived from ferc1_plants_utilitynames.csv + raw FERC1 name variants 2021-2023.
CO_PLANT_MAP: dict[tuple[int, str], int] = {
    (227, "comanche"):                   470,
    (205, "comanche"):                   470,
    ( 40, "comanche"):                   470,
    (227, "cherokee 4"):                 469,
    (227, "cherokee 5, 6, & 7"):         469,
    (227, "cherokee 3,4"):               469,
    # pawnee (6248) excluded: Form 1 2021-2023 reflects coal-era costs but plant
    # has since converted to Gas:ST — will receive ATB values in Sub-plan B2.
    (227, "hayden"):                     525,
    (303, "hayden"):                     525,
    (303, "hayden plant"):               525,
    (227, "craig"):                      6021,
    (303, "craig"):                      6021,
    (303, "craig 1,2"):                  6021,
    (303, "craig 3"):                    6021,
    (303, "craig plant"):                6021,
    (303, "craig station unit 3"):       6021,
    (303, "craig station units 1 & 2"):  6021,
    (303, "craig units 1 & 2"):          6021,
    (353, "craig station unit 3"):       6021,   # Tri-State G&T (largest Craig co-owner)
    (353, "craig station units 1 & 2"):  6021,
    (227, "fort st. vrain 1-4"):         6112,
    (227, "fort st. vrain 5-6"):         6112,
    (227, "rocky mountain"):             55835,
    (227, "blue spruce"):                55645,
    (227, "manchief"):                   55127,
    (227, "fort lupton"):                8067,
    (227, "fruita"):                     471,
    (227, "alamosa"):                    464,
    (227, "valmont 6, 7, & 8"):          55207,
    (227, "valmont 6, 7, &amp; 8"):      55207,  # HTML-escaped variant guard
}


# ---------------------------------------------------------------------------
# Form 1 — Sub-plan B2 Hydro constants
# ---------------------------------------------------------------------------

# PUDL S3 path for Schedule 408 (pumped storage hydroelectric plant statistics).
# Access via DuckDB with path-style URLs and us-west-2 region (avoids SSL cert
# errors caused by dots in the bucket name with virtual-hosted style).
FORM1_S408_URL = (
    "s3://pudl.catalyst.coop/stable"
    "/core_ferc1__yearly_pumped_storage_plants_sched408.parquet"
)
FORM1_HYDRO_YEARS = [2024, 2025]   # post-upgrade years; 2021-2023 reflect extended outage
FORM1_HYDRO_OUT   = (
    DATA_CLEANING / "resources" / "costs" / "form1" / "form1_co_hydro_om.csv"
)

# (utility_id_ferc1, lower(plant_name_ferc1)) → plant_id_eia
# Only Cabin Creek (467) is PSCo-owned and files Schedule 408.
# Mount Elbert (6208, WAPA) and Flatiron (518, Bureau of Reclamation) are
# federal facilities exempt from FERC Form 1 filing.
CO_HYDRO_PLANT_MAP: dict[tuple[int, str], int] = {
    (227, "cabin creek"): 467,
}

# ---------------------------------------------------------------------------
# ORNL empirical O&M medians for existing hydro (2020$)
# Source: Oladosu & Sasthav (2022), ORNL/TM-2021/2297, DOI: 10.2172/1845786
# Based on FERC Form 1 data for investor-owned U.S. hydro plants, 1994-2020.
# Inflated to 2025$ using CPI-U: 2020 avg 258.8 -> 2025 est. 320.4 (x1.237).
# For grouped conventional hydro: avg plant MW = MaxCap / count(plant_codes).
# For PSH: total O&M from Figure 24 (p. 26); fixed/variable split via ATB ratio.
# ---------------------------------------------------------------------------
ORNL_HYDRO_CPI_FACTOR: float = 1.237   # 2020$ -> 2025$

# Conventional hydro: Figure 12, p. 18 — size-class medians
# (upper_bound_mw, median_2020$/kw-yr): first entry where avg_plant_mw < upper_bound wins
ORNL_HYDRO_OM_BY_CLASS: list[tuple[float, float]] = [
    ( 10.0, 126.0),          # <10 MW:    median $126/kW (2020$) -> $156/kW (2025$)
    ( 30.0,  58.0),          # 10-30 MW:  median $ 58/kW (2020$) -> $ 72/kW (2025$)
    (100.0,  34.0),          # 30-100 MW: median $ 34/kW (2020$) -> $ 42/kW (2025$)
    (float("inf"), 23.0),    # >100 MW:   median $ 23/kW (2020$) -> $ 28/kW (2025$)
]

# Pumped storage hydro: Figure 24, p. 26 — all-plant median
ORNL_PSH_MEDIAN_2020: float = 14.0  # $14/kW (2020$) -> $17/kW (2025$)


# ---------------------------------------------------------------------------
# Form 1 Schedule 410 — CO wind plants with utility ownership (Sub-plan C)
# ---------------------------------------------------------------------------

FORM1_S410_URL = (
    "s3://pudl.catalyst.coop/stable"
    "/core_ferc1__yearly_small_plants_sched410.parquet"
)
FORM1_WIND_OUT = (
    DATA_CLEANING / "resources" / "costs" / "form1" / "form1_co_wind_om.csv"
)

# (plant_id_eia, utility_id_ferc1, name_substring, years_to_avg)
# name_substring matched case-insensitively against plant_name_ferc1.
# Busch Ranch restricted to 2021-2022: 2023 cap drops to 14.5 MW (partial
# retirement) vs 29 MW in EIA-860; 2021-2022 match the modeled capacity.
CO_WIND_S410_MAP: list[tuple[int, int, str, list[int]]] = [
    (60619, 227, "rush creek",      [2021, 2022, 2023]),
    (62952, 227, "cheyenne ridge",  [2021, 2022, 2023]),
    (60143, 309, "peak view",       [2021, 2022, 2023]),
    (57980, 309, "busch ranch",     [2021, 2022]),
]

# ---------------------------------------------------------------------------
# LBNL wind O&M by construction vintage (Sub-plan C)
# ---------------------------------------------------------------------------
# Source: LBNL Land-Based Wind Market Report 2024 Ed. (LBNL-2001724), Form 1
# national cap-weighted averages by vintage cohort. Values from pp.47-48 of the
# 2023 edition; verify against equivalent figure in the 2024 edition.
# (max_commission_year_inclusive, om_$/kw-yr)
LBNL_WIND_OM_BY_VINTAGE: list[tuple[int, float]] = [
    (2009, 20.0),   # pre-2010
    (2019, 21.0),   # 2010-2019
    (9999, 18.0),   # 2020+
]

# ---------------------------------------------------------------------------
# LBNL solar O&M (Sub-plan C)
# ---------------------------------------------------------------------------
# Source: LBNL Utility-Scale Solar 2024 Ed. (LBNL-2001700), p.25.
# Form 1 national medians; split by status_category in colorado_resources.csv.
LBNL_SOLAR_OM_PROPOSED:  float = 11.0   # $/kWac-yr, newest cohort (2023 obs.)
LBNL_SOLAR_OM_OPERATING: float = 22.0   # $/kWac-yr, all-ages fleet median

GENERATORS_CSV = (
    DATA_CLEANING / "resources" / "eia860" / "colorado_generators.csv"
)


# ---------------------------------------------------------------------------
# ATB loading
# ---------------------------------------------------------------------------

def download_atb(force: bool = False) -> Path:
    if ATB_CACHE.exists() and not force:
        size_mb = ATB_CACHE.stat().st_size / 1_048_576
        print(f"  ATB cached ({size_mb:.1f} MB): {ATB_CACHE.name}")
        return ATB_CACHE
    ATB_CACHE.parent.mkdir(parents=True, exist_ok=True)
    print("  Downloading NREL ATB 2024 from OEDI (this may take a minute)...")
    urllib.request.urlretrieve(ATB_URL, ATB_CACHE)
    size_mb = ATB_CACHE.stat().st_size / 1_048_576
    print(f"  Saved ({size_mb:.1f} MB): {ATB_CACHE}")
    return ATB_CACHE


def _verify_atb_columns(df: pd.DataFrame) -> None:
    required = [
        "technology", "core_metric_parameter", "core_metric_variable",
        "scenario", "units", "value", "techdetail",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"ATB CSV missing expected columns: {missing}\n"
            f"Columns present: {sorted(df.columns.tolist())}"
        )


def load_atb_raw(csv_path: Path) -> pd.DataFrame:
    """Load ATB CSV; filter to Moderate scenario and O&M parameters only."""
    print(f"  Loading ATB 2024 (large file -- may take a moment)...")
    df = pd.read_csv(csv_path, low_memory=False)
    _verify_atb_columns(df)

    if PRINT_ATB_TECHS:
        techs = sorted(df["technology"].dropna().unique())
        print(f"\n  ATB technology labels ({len(techs)} total):")
        for t in techs:
            print(f"    {t}")
        print()

    df["scenario"] = df["scenario"].str.lower().str.strip()
    df["core_metric_variable"] = pd.to_numeric(df["core_metric_variable"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    mask = (
        (df["scenario"] == ATB_SCENARIO)
        & (df["core_metric_parameter"].isin([ATB_PARAM_FIXED, ATB_PARAM_VOM]))
        & (df["core_metric_variable"].isin(ATB_YEARS))
    )
    filtered = df[mask].copy()
    print(f"  Filtered to {len(filtered):,} rows (Moderate, O&M, {ATB_YEARS[0]}-{ATB_YEARS[-1]})")
    return filtered


# ---------------------------------------------------------------------------
# Lookup construction
# ---------------------------------------------------------------------------

def _select_rows(df: pd.DataFrame, spec: dict, param: str, year: int) -> pd.DataFrame:
    """Return rows matching tech/techdetail spec, param, and year."""
    mask = (
        (df["technology"] == spec["atb_tech"])
        & (df["core_metric_parameter"] == param)
        & (df["core_metric_variable"] == year)
    )
    sub = df[mask]

    # Apply techdetail filters
    if "detail_exact" in spec:
        sub = sub[sub["techdetail"] == spec["detail_exact"]]
    elif "detail_contains" in spec:
        pat = spec["detail_contains"]
        sub = sub[sub["techdetail"].str.contains(pat, case=False, na=False)]
        if "detail_excludes" in spec:
            excl = spec["detail_excludes"]
            sub = sub[~sub["techdetail"].str.contains(excl, case=False, na=False)]

    return sub


def _atb_value(df: pd.DataFrame, spec: dict, param: str, year: int) -> float | None:
    """Return median O&M value for a tech spec / param / year combination."""
    sub = _select_rows(df, spec, param, year)
    vals = sub["value"].dropna()
    if vals.empty:
        return None
    return float(vals.median())


def _atb_value_with_fallback(df: pd.DataFrame, spec: dict, param: str, year: int) -> float | None:
    """Like _atb_value but uses nearest available year if target year has no data."""
    v = _atb_value(df, spec, param, year)
    if v is not None:
        return v

    # Find all years with data for this tech/param
    mask = (
        (df["technology"] == spec["atb_tech"])
        & (df["core_metric_parameter"] == param)
    )
    sub = df[mask]
    if "detail_exact" in spec:
        sub = sub[sub["techdetail"] == spec["detail_exact"]]
    elif "detail_contains" in spec:
        pat = spec["detail_contains"]
        sub = sub[sub["techdetail"].str.contains(pat, case=False, na=False)]
        if "detail_excludes" in spec:
            excl = spec["detail_excludes"]
            sub = sub[~sub["techdetail"].str.contains(excl, case=False, na=False)]

    available = sub["core_metric_variable"].dropna().unique()
    if len(available) == 0:
        return None

    # Use nearest year (minimum distance); prefer earlier over later for extrapolation
    nearest = int(min(available, key=lambda y: (abs(y - year), y)))
    return _atb_value(df, spec, param, nearest)


def build_atb_om_lookup(atb_raw: pd.DataFrame) -> pd.DataFrame:
    """
    For each TechType x year: extract Fixed O&M ($/kW-yr) and Variable O&M ($/MWh).
    Compute fixed_share = fixed_om / (fixed_om + vom * 8760 * CF / 1000).
    """
    rows = []
    for tech_class, spec in ATB_TECH_SPEC.items():
        cf = REF_CF.get(tech_class, 0.50)
        vom_default = spec.get("vom_default", None)
        use_fallback = spec.get("year_fallback", False)

        get_val = _atb_value_with_fallback if use_fallback else _atb_value

        for year in ATB_YEARS:
            fixed = get_val(atb_raw, spec, ATB_PARAM_FIXED, year)
            vom   = get_val(atb_raw, spec, ATB_PARAM_VOM,   year)

            if vom is None and vom_default is not None:
                vom = vom_default

            if fixed is None or vom is None:
                continue

            # fixed_share: fraction of total annual O&M that is fixed cost
            # Annual VOM per kW-yr = vom [$/MWh] x 8760 [hr/yr] x CF x (1 MWh / 1000 kWh)
            annual_vom_kw = vom * 8760 * cf / 1000
            denom = fixed + annual_vom_kw
            fixed_share = fixed / denom if denom > 0 else 1.0

            rows.append({
                "tech_class":  tech_class,
                "atb_year":    year,
                "scenario":    "Moderate",
                "fixed_om":    round(fixed, 2),
                "variable_om": round(vom, 4),
                "ref_cf":      cf,
                "fixed_share": round(fixed_share, 4),
            })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Form 1 — Sub-plan B1 functions
# ---------------------------------------------------------------------------

def build_form1_co_extract(raw_csv: Path) -> pd.DataFrame:
    """
    Load raw FERC1 Schedule 402; filter to CO utilities + 2021-2023;
    attach plant_id_eia via CO_PLANT_MAP; compute 3-year average non-fuel
    O&M ($/kW-yr) and actual capacity factor per plant_id_eia.
    """
    print(f"  Loading raw FERC1 Schedule 402 ({raw_csv.stat().st_size / 1e6:.1f} MB)...")
    df = pd.read_csv(raw_csv, low_memory=False)

    df = df[
        df["utility_id_ferc1"].isin(FORM1_CO_UTIL_IDS)
        & df["report_year"].isin(FORM1_YEARS)
    ].copy()
    print(f"  CO utility rows (2021-2023): {len(df)}")

    # Attach plant_id_eia via lookup; rows not in map → None → dropped
    keys = list(zip(
        df["utility_id_ferc1"].astype(int),
        df["plant_name_ferc1"].astype(str).str.lower().str.strip(),
    ))
    df["plant_id_eia"] = [CO_PLANT_MAP.get(k) for k in keys]

    # Drop excluded (utility_id, plant_id_eia) co-owner pairs
    if FORM1_EXCLUDE_PAIRS:
        pair_col = list(zip(
            df["utility_id_ferc1"].astype(int),
            df["plant_id_eia"].fillna(-1).astype(int),
        ))
        keep = [p not in FORM1_EXCLUDE_PAIRS for p in pair_col]
        n_excl = len(df) - sum(keep)
        if n_excl:
            print(f"  Excluded {n_excl} rows per FORM1_EXCLUDE_PAIRS")
        df = df[keep].copy()

    # Per-plant year overrides: drop years not in the allowed list for that plant
    if FORM1_PLANT_YEARS:
        keep = pd.Series(True, index=df.index)
        for pid, allowed_yrs in FORM1_PLANT_YEARS.items():
            keep &= ~((df["plant_id_eia"] == pid) & ~df["report_year"].isin(allowed_yrs))
        n_excl = int((~keep).sum())
        if n_excl:
            print(f"  Excluded {n_excl} rows per FORM1_PLANT_YEARS overrides")
        df = df[keep].copy()

    # Drop unmatched rows, aggregate "total" rows (capacity == 0 or null)
    df = df.dropna(subset=["plant_id_eia", "capacity_mw", "opex_production_total", "opex_fuel"])
    df = df[df["capacity_mw"] > 0]

    # Per-row non-fuel O&M and actual CF
    df["non_fuel_om"] = (df["opex_production_total"] - df["opex_fuel"]).clip(lower=0)
    df["actual_cf"]   = (df["net_generation_mwh"] / (df["capacity_mw"] * 8760)).clip(0.01, 1.0)

    # Sum across co-owners per (plant_id_eia, year)
    yr_grp = df.groupby(["plant_id_eia", "report_year"], as_index=False).agg(
        capacity_mw=("capacity_mw",        "sum"),
        non_fuel_om=("non_fuel_om",        "sum"),
        net_gen_mwh=("net_generation_mwh", "sum"),
    )
    yr_grp["non_fuel_om_kw"] = yr_grp["non_fuel_om"] / (yr_grp["capacity_mw"] * 1000)
    yr_grp["actual_cf"]      = (
        yr_grp["net_gen_mwh"] / (yr_grp["capacity_mw"] * 8760)
    ).clip(0.01, 1.0)

    # 3-year average
    form1 = yr_grp.groupby("plant_id_eia", as_index=False).agg(
        non_fuel_om_kw=("non_fuel_om_kw", "mean"),
        actual_cf     =("actual_cf",      "mean"),
        capacity_mw   =("capacity_mw",    "mean"),
    )
    form1["plant_id_eia"] = form1["plant_id_eia"].astype(int)

    print(f"\n  Form 1 CO plant rates (3-yr avg {FORM1_YEARS[0]}-{FORM1_YEARS[-1]}):")
    print(f"  {'plant_id_eia':>12}  {'non_fuel $/kW-yr':>17}  {'actual_CF':>9}  {'cap_mw':>7}")
    print(f"  {'-'*52}")
    for _, r in form1.sort_values("plant_id_eia").iterrows():
        print(
            f"  {int(r.plant_id_eia):>12}  {r.non_fuel_om_kw:>17.2f}  "
            f"{r.actual_cf:>9.3f}  {r.capacity_mw:>7.1f}"
        )
    return form1


def enrich_with_form1(
    resources: pd.DataFrame,
    form1_rates: pd.DataFrame,
    atb_lookup: pd.DataFrame,
    om_source_label: str = "form1_2021_2023",
    allowed_tech_types: set | None = None,
) -> pd.DataFrame:
    """
    For each resource with a single plant_code that matches a plant_id_eia in
    form1_rates: derive FixedRate and EnCost using the ATB fixed/variable ratio
    (recomputed at the plant's actual_cf) applied to the Form 1 non-fuel O&M total.
    Skips resources that already have om_source set (from a prior enrichment pass).
    """
    # plant_id_eia → {non_fuel_om_kw, actual_cf}
    f1 = form1_rates.set_index("plant_id_eia")

    # TechType → ATB fixed_om and variable_om at ATB_YEAR
    atb_yr = (
        atb_lookup[atb_lookup["atb_year"] == ATB_YEAR]
        .set_index("tech_class")[["fixed_om", "variable_om"]]
    )

    matched = 0
    for idx, row in resources.iterrows():
        if pd.notna(row.get("om_source")):
            continue   # already assigned by a prior enrichment pass

        raw_codes = row.get("plant_codes")
        if pd.isna(raw_codes):
            continue

        codes_str = [c.strip() for c in str(raw_codes).split(";") if c.strip()]
        try:
            int_codes = [int(c) for c in codes_str]
        except ValueError:
            continue

        # Only proceed if every code resolves to Form 1 data
        matched_ids = [c for c in int_codes if c in f1.index]
        if len(matched_ids) != len(int_codes) or len(matched_ids) == 0:
            continue   # skip grouped resources where some codes aren't in Form 1

        unique_plants = set(matched_ids)
        if len(unique_plants) != 1:
            continue   # multiple distinct Form 1 plants → ambiguous

        plant_id = next(iter(unique_plants))
        f1_row   = f1.loc[plant_id]

        tech = row.get("TechType", "")
        if allowed_tech_types is not None and tech not in allowed_tech_types:
            continue
        if tech not in atb_yr.index:
            continue

        non_fuel_om_kw = float(f1_row["non_fuel_om_kw"])
        actual_cf      = float(f1_row["actual_cf"])
        fixed_atb      = float(atb_yr.loc[tech, "fixed_om"])
        vom_atb        = float(atb_yr.loc[tech, "variable_om"])

        annual_vom_kw = vom_atb * 8760 * actual_cf / 1000
        denom         = fixed_atb + annual_vom_kw
        fixed_share   = fixed_atb / denom if denom > 0 else 1.0

        fixed_rate = non_fuel_om_kw * fixed_share
        en_cost    = (
            non_fuel_om_kw * (1.0 - fixed_share) / (8760 * actual_cf / 1000)
            if actual_cf > 0 else 0.0
        )

        resources.at[idx, "FixedRate"]  = round(fixed_rate, 2)
        resources.at[idx, "EnCost"]     = round(en_cost, 4)
        resources.at[idx, "om_source"]  = om_source_label
        matched += 1

    print(f"\n  {'Resource':<44} {'TechType':<10} {'$/kW-yr':>8} {'CF':>6} {'Fixed%':>7} {'FixedRate':>10} {'EnCost':>8}")
    print(f"  {'-'*96}")
    for _, r in resources[resources["om_source"] == om_source_label].iterrows():
        pid = int(r["plant_codes"].strip().split(";")[0])
        if pid not in f1.index:
            continue   # skip resources matched in a prior enrichment pass with same label
        f1r = f1.loc[pid]
        print(
            f"  {r['Name']:<44} {r['TechType']:<10} "
            f"{f1r['non_fuel_om_kw']:>8.2f} {f1r['actual_cf']:>6.3f} "
            f"{(r['FixedRate'] / f1r['non_fuel_om_kw'] * 100):>6.1f}%"
            f" {r['FixedRate']:>10.2f} {r['EnCost']:>8.4f}"
        )

    n_total     = len(resources)
    n_unassigned = int(resources["om_source"].isna().sum())
    print(f"\n  {matched} of {n_total} resources matched  ({n_unassigned} still unassigned)")
    return resources


# ---------------------------------------------------------------------------
# Form 1 — Sub-plan B2 Hydro functions
# ---------------------------------------------------------------------------

def build_form1_hydro_extract() -> pd.DataFrame:
    """
    Query PUDL Schedule 408 (pumped storage) from S3 for CO utilities;
    attach plant_id_eia via CO_HYDRO_PLANT_MAP; compute 3-year average
    non-fuel O&M ($/kW-yr) and actual CF per plant_id_eia.

    opex_total in Schedule 408 IS the total non-fuel O&M (hydro has no fuel cost).
    """
    try:
        import duckdb
    except ImportError:
        import sys
        raise ImportError(
            f"duckdb not found in {sys.executable}\n"
            f"Fix: {sys.executable} -m pip install duckdb"
        )

    print(f"  Querying PUDL Schedule 408 (pumped storage) from S3...")
    conn = duckdb.connect()
    conn.execute("LOAD httpfs;")
    conn.execute("SET s3_url_style='path'; SET s3_region='us-west-2';")

    util_ids = ", ".join(str(x) for x in FORM1_CO_UTIL_IDS)
    years    = ", ".join(str(y) for y in FORM1_HYDRO_YEARS)

    df = conn.execute(f"""
        SELECT utility_id_ferc1, report_year, plant_name_ferc1,
               capacity_mw, net_generation_mwh, opex_total
        FROM read_parquet('{FORM1_S408_URL}')
        WHERE utility_id_ferc1 IN ({util_ids})
          AND report_year IN ({years})
    """).fetchdf()

    print(f"  CO utility pumped-storage rows ({FORM1_HYDRO_YEARS[0]}-{FORM1_HYDRO_YEARS[-1]}): {len(df)}")

    keys = list(zip(
        df["utility_id_ferc1"].astype(int),
        df["plant_name_ferc1"].astype(str).str.lower().str.strip(),
    ))
    df["plant_id_eia"] = [CO_HYDRO_PLANT_MAP.get(k) for k in keys]

    df = df.dropna(subset=["plant_id_eia", "capacity_mw", "opex_total"])
    df = df[df["capacity_mw"] > 0]

    df["non_fuel_om"] = df["opex_total"].clip(lower=0)
    df["actual_cf"]   = (df["net_generation_mwh"] / (df["capacity_mw"] * 8760)).clip(0.01, 1.0)

    yr_grp = df.groupby(["plant_id_eia", "report_year"], as_index=False).agg(
        capacity_mw=("capacity_mw",        "sum"),
        non_fuel_om=("non_fuel_om",        "sum"),
        net_gen_mwh=("net_generation_mwh", "sum"),
    )
    yr_grp["non_fuel_om_kw"] = yr_grp["non_fuel_om"] / (yr_grp["capacity_mw"] * 1000)
    yr_grp["actual_cf"]      = (
        yr_grp["net_gen_mwh"] / (yr_grp["capacity_mw"] * 8760)
    ).clip(0.01, 1.0)

    form1_hydro = yr_grp.groupby("plant_id_eia", as_index=False).agg(
        non_fuel_om_kw=("non_fuel_om_kw", "mean"),
        actual_cf     =("actual_cf",      "mean"),
        capacity_mw   =("capacity_mw",    "mean"),
    )
    form1_hydro["plant_id_eia"] = form1_hydro["plant_id_eia"].astype(int)

    n_yrs = len(FORM1_HYDRO_YEARS)
    print(f"\n  Form 1 CO pumped-storage rates ({n_yrs}-yr avg, {FORM1_HYDRO_YEARS[0]}-{FORM1_HYDRO_YEARS[-1]}):")
    print(f"  {'plant_id_eia':>12}  {'non_fuel $/kW-yr':>17}  {'actual_CF':>9}  {'cap_mw':>7}")
    print(f"  {'-'*52}")
    for _, r in form1_hydro.sort_values("plant_id_eia").iterrows():
        print(
            f"  {int(r.plant_id_eia):>12}  {r.non_fuel_om_kw:>17.2f}  "
            f"{r.actual_cf:>9.3f}  {r.capacity_mw:>7.1f}"
        )
    return form1_hydro


def enrich_hydro_atb_fallback(
    resources: pd.DataFrame,
    atb_lookup: pd.DataFrame,
) -> pd.DataFrame:
    """
    For unassigned hydro resources:
      Hydro:Pumped  -> ORNL PSH median (Fig 24, p.26) as total O&M; ATB fixed/variable ratio.
      Hydro         -> ORNL FERC Form 1 median by individual plant size class
                       (Oladosu & Sasthav 2022, Figure 12 p.18, DOI 10.2172/1845786),
                       inflated to 2025$ via CPI-U x1.237. EnCost = 0 (no VOM).
                       Average plant MW = MaxCap / count(plant_codes entries).
    """
    atb_yr = (
        atb_lookup[atb_lookup["atb_year"] == ATB_YEAR]
        .set_index("tech_class")[["fixed_om", "variable_om"]]
    )

    matched = 0
    summary = []

    for idx, row in resources.iterrows():
        if pd.notna(row.get("om_source")):
            continue
        tech = row.get("TechType", "")
        if tech not in {"Hydro", "Hydro:Pumped"}:
            continue

        if tech == "Hydro:Pumped":
            if tech not in atb_yr.index:
                continue
            # ORNL empirical median (Fig 24, p.26) as total; ATB ratio for fixed/variable split
            total_om    = ORNL_PSH_MEDIAN_2020 * ORNL_HYDRO_CPI_FACTOR
            fixed_atb   = float(atb_yr.loc[tech, "fixed_om"])
            vom_atb     = float(atb_yr.loc[tech, "variable_om"])
            cf          = REF_CF.get(tech, 0.15)
            vom_kw      = vom_atb * 8760 * cf / 1000
            fixed_share = fixed_atb / (fixed_atb + vom_kw) if (fixed_atb + vom_kw) > 0 else 1.0
            fixed_rate  = total_om * fixed_share
            vom         = (total_om * (1 - fixed_share) / (8760 * cf / 1000)) if cf > 0 else 0.0
            source      = "ornl_ferc1_median"
            size_label  = ""
        else:
            raw_codes  = row.get("plant_codes", "")
            n_plants   = max(1, len([c for c in str(raw_codes).split(";") if c.strip()])) \
                         if pd.notna(raw_codes) else 1
            avg_mw     = float(row.get("MaxCap", 0)) / n_plants
            median_2020 = next(v for (lim, v) in ORNL_HYDRO_OM_BY_CLASS if avg_mw < lim)
            fixed_rate  = round(median_2020 * ORNL_HYDRO_CPI_FACTOR, 2)
            vom         = 0.0
            source      = "ornl_ferc1_median"
            size_label  = (
                "<10 MW"    if avg_mw <  10  else
                "10-30 MW"  if avg_mw <  30  else
                "30-100 MW" if avg_mw < 100  else
                ">100 MW"
            )

        resources.at[idx, "FixedRate"] = round(fixed_rate, 2)
        resources.at[idx, "EnCost"]    = round(vom, 4)
        resources.at[idx, "om_source"] = source
        matched += 1
        summary.append((
            row["Name"], tech,
            float(row.get("MaxCap", 0)),
            int(1 if tech == "Hydro:Pumped" else max(1, len([c for c in str(row.get("plant_codes","")).split(";") if c.strip()]))),
            size_label, fixed_rate, vom, source,
        ))

    if summary:
        print(f"\n  Hydro fallback assignments ({matched} resources):")
        print(f"  {'Name':<40} {'Tech':<12} {'Cap':>6} {'N':>3} {'Size class':<11} {'FixedRate':>10} {'EnCost':>8}  Source")
        print(f"  {'-'*100}")
        for name, tech, cap, n, sz, fr, ec, src in summary:
            print(f"  {name:<40} {tech:<12} {cap:>6.1f} {n:>3} {sz:<11} {fr:>10.2f} {ec:>8.4f}  {src}")

    return resources, matched


# ---------------------------------------------------------------------------
# Sub-plan C — Wind, Solar, Battery O&M
# ---------------------------------------------------------------------------

def build_form1_wind_extract() -> pd.DataFrame:
    """
    Query PUDL Schedule 410 for PSCo (227) and Black Hills CO (309) wind plants.
    Returns one row per plant in CO_WIND_S410_MAP with the avg $/kW-yr over the
    allowed years for that plant.
    """
    try:
        import duckdb
    except ImportError:
        raise ImportError(
            f"duckdb not found — fix: .venv\\Scripts\\python.exe -m pip install duckdb"
        )

    conn = duckdb.connect()
    conn.execute("LOAD httpfs;")
    conn.execute("SET s3_url_style='path'; SET s3_region='us-west-2';")

    print(f"  Querying PUDL Schedule 410 (wind) from S3...")
    df = conn.execute(f"""
        SELECT utility_id_ferc1, report_year, plant_name_ferc1,
               capacity_mw, opex_operations, opex_maintenance
        FROM read_parquet('{FORM1_S410_URL}')
        WHERE utility_id_ferc1 IN (227, 309)
          AND fuel_type = 'wind'
          AND report_year BETWEEN 2021 AND 2023
          AND capacity_mw > 0
    """).df()

    records = []
    for plant_id, util_id, name_sub, allowed_years in CO_WIND_S410_MAP:
        mask = (
            (df["utility_id_ferc1"] == util_id)
            & df["plant_name_ferc1"].str.lower().str.contains(name_sub, na=False)
            & df["report_year"].isin(allowed_years)
        )
        rows = df[mask].copy()
        if rows.empty:
            print(f"  WARNING: no Schedule 410 rows matched for plant_id_eia={plant_id} ('{name_sub}')")
            continue
        rows["om_kw_yr"] = (
            (rows["opex_operations"] + rows["opex_maintenance"])
            / (rows["capacity_mw"] * 1000)
        )
        records.append({
            "plant_id_eia":    plant_id,
            "utility_id_ferc1": util_id,
            "om_kw":           round(float(rows["om_kw_yr"].mean()), 2),
            "capacity_mw":     round(float(rows["capacity_mw"].mean()), 1),
            "n_years":         len(rows),
        })

    form1_wind = pd.DataFrame(records)
    print(f"\n  Form 1 Schedule 410 CO wind rates:")
    print(f"  {'plant_id_eia':>12} {'om_kw':>8} {'cap_mw':>8} {'n_yrs':>6}")
    print(f"  {'-'*40}")
    for _, r in form1_wind.iterrows():
        print(f"  {int(r.plant_id_eia):>12} {r.om_kw:>8.2f} {r.capacity_mw:>8.1f} {int(r.n_years):>6}")
    return form1_wind


def build_wind_plant_rates(
    form1_wind: pd.DataFrame,
    gen_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Per-EIA-plant O&M rate table for all CO wind plants.
    Form 1 rate for the 4 utility-owned plants; LBNL vintage lookup for the rest.
    gen_df must already be filtered to tech_type == "Wind" and have commission_year column.
    """
    f1_idx  = set(form1_wind["plant_id_eia"].astype(int))
    f1_rate = form1_wind.set_index("plant_id_eia")["om_kw"]

    # Plant-level capacity and capacity-weighted avg commission year
    cap_by_plant  = gen_df.groupby("plant_code")["summer_mw"].sum()
    wsum_by_plant = (gen_df.assign(ws=gen_df["summer_mw"] * gen_df["commission_year"])
                     .groupby("plant_code")["ws"].sum())
    avg_yr_by_plant = wsum_by_plant / cap_by_plant.replace(0, float("nan"))

    records = []
    for pid in sorted(cap_by_plant.index):
        pid = int(pid)
        cap = float(cap_by_plant.get(pid, 0))
        avg_yr_raw = avg_yr_by_plant.get(pid, float("nan"))
        avg_yr = float(avg_yr_raw) if pd.notna(avg_yr_raw) else float("nan")

        if pid in f1_idx:
            om_kw  = float(f1_rate.loc[pid])
            source = "form1_wind"
        else:
            yr = int(round(avg_yr)) if pd.notna(avg_yr) else 2015
            om_kw  = next(v for (lim, v) in LBNL_WIND_OM_BY_VINTAGE if yr <= lim)
            source = "lbnl_wind_2024"

        records.append({
            "plant_id_eia":        pid,
            "om_kw":               round(om_kw, 2),
            "source":              source,
            "avg_commission_year": round(avg_yr, 1) if pd.notna(avg_yr) else None,
            "capacity_mw":         round(cap, 1),
        })

    plant_rates = pd.DataFrame(records)
    print(f"\n  Per-plant CO wind O&M rates ({len(plant_rates)} plants):")
    print(f"  {'plant_id_eia':>12} {'avg_yr':>7} {'om_kw':>8} {'cap_mw':>8}  source")
    print(f"  {'-'*58}")
    for _, r in plant_rates.iterrows():
        yr_str = f"{r['avg_commission_year']:.0f}" if pd.notna(r["avg_commission_year"]) else "  n/a"
        print(f"  {int(r.plant_id_eia):>12} {yr_str:>7} {r.om_kw:>8.2f} {r.capacity_mw:>8.1f}  {r.source}")
    return plant_rates


def enrich_wind_all(
    resources: pd.DataFrame,
    plant_rates: pd.DataFrame,
    gen_df: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """
    Assigns FixedRate to each Wind resource as the capacity-weighted average of
    its constituent plants' per-plant rates (Form 1 or LBNL vintage). VOM = 0.
    om_source = 'form1_lbnl_blend_2024' if any Form 1 plant in group, else 'lbnl_wind_2024'.
    """
    rate_idx = plant_rates.set_index("plant_id_eia")
    # Plant-level capacity from gen_df for weighting (may differ from plant_rates for multi-unit plants)
    plant_cap = gen_df.groupby("plant_code")["summer_mw"].sum()

    matched = 0
    summary = []

    for idx, row in resources.iterrows():
        if pd.notna(row.get("om_source")):
            continue
        if row.get("TechType") != "Wind":
            continue

        raw_codes = row.get("plant_codes")
        if pd.isna(raw_codes):
            continue
        codes = [int(c.strip()) for c in str(raw_codes).split(";") if c.strip()]

        weighted_sum = 0.0
        total_cap    = 0.0
        n_form1      = 0
        n_lbnl       = 0

        for code in codes:
            if code not in rate_idx.index:
                print(f"  WARNING: plant_code {code} not in plant_rates; skipping")
                continue
            pr  = rate_idx.loc[code]
            cap = float(plant_cap.get(code, pr["capacity_mw"]))
            weighted_sum += float(pr["om_kw"]) * cap
            total_cap    += cap
            if pr["source"] == "form1_wind":
                n_form1 += 1
            else:
                n_lbnl += 1

        if total_cap <= 0:
            continue

        blended_om = weighted_sum / total_cap
        om_source  = "form1_lbnl_blend_2024" if n_form1 > 0 else "lbnl_wind_2024"

        resources.at[idx, "FixedRate"] = round(blended_om, 2)
        resources.at[idx, "EnCost"]    = 0.0
        resources.at[idx, "om_source"] = om_source
        matched += 1
        summary.append((row["Name"], float(row["MaxCap"]), round(blended_om, 2), n_form1, n_lbnl, om_source))

    if summary:
        print(f"\n  Wind O&M assignments ({matched} resources):")
        print(f"  {'Name':<44} {'MaxCap':>7} {'$/kW':>7} {'F1':>4} {'LBNL':>5}  source")
        print(f"  {'-'*84}")
        for name, cap, om, nf, nl, src in summary:
            print(f"  {name:<44} {cap:>7.1f} {om:>7.2f} {nf:>4} {nl:>5}  {src}")
    return resources, matched


def enrich_solar_lbnl(resources: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """
    Assigns LBNL solar O&M by status_category:
      proposed  -> LBNL_SOLAR_OM_PROPOSED  ($11/kWac-yr, newest cohort, 2023 obs.)
      operating -> LBNL_SOLAR_OM_OPERATING ($22/kWac-yr, all-ages fleet median)
    Source: LBNL Utility-Scale Solar 2024 Ed. (LBNL-2001700), p.25.
    """
    matched    = 0
    n_proposed = 0
    n_oper     = 0

    for idx, row in resources.iterrows():
        if pd.notna(row.get("om_source")):
            continue
        if row.get("TechType") != "Solar:PV":
            continue

        status = str(row.get("status_category", "")).lower()
        if status == "proposed":
            om_kw = LBNL_SOLAR_OM_PROPOSED
            n_proposed += 1
        else:
            om_kw = LBNL_SOLAR_OM_OPERATING
            n_oper += 1

        resources.at[idx, "FixedRate"] = om_kw
        resources.at[idx, "EnCost"]    = 0.0
        resources.at[idx, "om_source"] = "lbnl_solar_2024"
        matched += 1

    print(
        f"\n  Solar:PV LBNL assignments: "
        f"{n_oper} operating @ ${LBNL_SOLAR_OM_OPERATING}/kW,  "
        f"{n_proposed} proposed @ ${LBNL_SOLAR_OM_PROPOSED}/kW  "
        f"({matched} total)"
    )
    return resources, matched


def enrich_battery_atb(
    resources: pd.DataFrame,
    atb_lookup: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """Assigns ATB 2024 Moderate fixed and variable O&M to Storage:Battery resources."""
    atb_yr = (
        atb_lookup[atb_lookup["atb_year"] == ATB_YEAR]
        .set_index("tech_class")[["fixed_om", "variable_om"]]
    )
    if "Storage:Battery" not in atb_yr.index:
        print("  WARNING: Storage:Battery not in ATB lookup — battery enrichment skipped")
        return resources, 0

    fixed_om = float(atb_yr.loc["Storage:Battery", "fixed_om"])
    var_om   = float(atb_yr.loc["Storage:Battery", "variable_om"])
    matched  = 0

    for idx, row in resources.iterrows():
        if pd.notna(row.get("om_source")):
            continue
        if row.get("TechType") != "Storage:Battery":
            continue
        resources.at[idx, "FixedRate"] = round(fixed_om, 2)
        resources.at[idx, "EnCost"]    = round(var_om, 4)
        resources.at[idx, "om_source"] = "atb_2024"
        matched += 1

    print(
        f"\n  Storage:Battery ATB 2024 Moderate: "
        f"FixedRate=${fixed_om:.2f}/kW-yr, EnCost=${var_om:.4f}/MWh  "
        f"({matched} resources)"
    )
    return resources, matched


# ---------------------------------------------------------------------------
# Sub-plan D — Pueblo Airport CC (Form 1) + ATB thermal fallback
# ---------------------------------------------------------------------------

# Form 1 CO coal peers used to proxy Rawhide and Ray Nixon O&M.
# ATB Coal-new ($85.70/kW fixed) is a new-build planning cost — not appropriate for
# existing plants. These three peers are the only CO coal plants with Form 1 coverage.
COAL_FORM1_PEER_IDS: list[int] = [470, 525, 6021]  # Comanche, Hayden, Craig

# Per-resource ATB tech-class overrides for enrich_atb_fallback().
# Use when a resource's TechType maps to a poor ATB proxy (e.g. Gas:ST → CT)
# and a different tech-class is more appropriate.
# Pawnee (Gas:ST): post-coal-conversion steam plant retains boiler + full steam
# turbine; Gas:CC ATB covers steam turbine maintenance and is a better proxy
# than CT ATB, which assumes no steam cycle. Conversion confirmed end-of-2025;
# no gas-era Form 1 data available yet (all 2024-2025 Form 1 reflects coal ops).
RESOURCE_ATB_OVERRIDES: dict[str, str] = {
    "pawnee__1": "Gas:CC",
}

def build_form1_pueblo_airport_cc() -> pd.DataFrame:
    """
    Extract Form 1 Schedule 402 non-fuel O&M for Pueblo Airport Generating Station
    CC/steam portion (plant 56998, Black Hills CO Electric, utility 309).

    'Units 1 & 2' rows (200 MW, NGCC steam) are matched by exact name set;
    'Unit 6' (42 MW) and 'Pueblo Diesels' are intentionally excluded.
    The GT units at the same plant do not appear in Schedule 402.

    Returns a one-row DataFrame compatible with enrich_with_form1() (columns:
    plant_id_eia, non_fuel_om_kw, actual_cf, capacity_mw).
    """
    df = pd.read_csv(FORM1_RAW_CSV, low_memory=False)

    # Exact lower-cased plant_name_ferc1 variants seen in 2021-2023 for units 1 & 2 only
    pa_names = {
        "units 1&2 pueblo airport",
        "pueblo airport generation station - units 1 & 2",
        "pueblo airport generation station- unit 1 & 2",
    }
    mask = (
        (df["utility_id_ferc1"] == 309)
        & df["plant_name_ferc1"].str.lower().str.strip().isin(pa_names)
        & df["report_year"].isin(FORM1_YEARS)
        & (df["capacity_mw"] > 0)
    )
    rows = df[mask].copy()

    if rows.empty:
        print("  WARNING: Pueblo Airport CC (utility 309, units 1&2) not found in Form 1 S402")
        return pd.DataFrame()

    rows["non_fuel_om"] = (rows["opex_production_total"] - rows["opex_fuel"]).clip(lower=0)
    rows["non_fuel_om_kw"] = rows["non_fuel_om"] / (rows["capacity_mw"] * 1000)
    rows["actual_cf"]      = (rows["net_generation_mwh"] / (rows["capacity_mw"] * 8760)).clip(0.01, 1.0)

    result = pd.DataFrame([{
        "plant_id_eia":   56998,
        "non_fuel_om_kw": round(float(rows["non_fuel_om_kw"].mean()), 2),
        "actual_cf":      round(float(rows["actual_cf"].mean()), 3),
        "capacity_mw":    round(float(rows["capacity_mw"].mean()), 1),
    }])

    n = len(rows)
    print(
        f"\n  Pueblo Airport CC (plant 56998, Black Hills CO utility 309): "
        f"${result.iloc[0]['non_fuel_om_kw']:.2f}/kW-yr  "
        f"CF={result.iloc[0]['actual_cf']:.3f}  "
        f"cap={result.iloc[0]['capacity_mw']:.0f} MW  "
        f"({n}-yr avg {FORM1_YEARS[0]}-{FORM1_YEARS[-1]})"
    )
    return result


def enrich_coal_peer_proxy(
    resources: pd.DataFrame,
    form1_co: pd.DataFrame,
    atb_lookup: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """
    Assigns O&M to existing Coal resources lacking Form 1 coverage (Rawhide,
    Ray Nixon) using a capacity-weighted average of CO Form 1 coal peers
    (Comanche 470, Hayden 525, Craig 6021).

    ATB Coal-new ($85.70/kW fixed, $9.22/MWh VOM) is a new-build planning cost;
    Form 1 peers reflect actual existing-plant operational costs and are the
    appropriate proxy for similarly-aged CO coal units that don't file Form 1.

    Fixed/variable split uses the ATB Coal ratio at the peer-average actual CF,
    consistent with how the Form 1 peers were split in enrich_with_form1().
    Proposed Coal resources are skipped (ATB new-build values apply in fallback).
    om_source = 'form1_co_coal_peer_proxy'
    """
    peers = form1_co[form1_co["plant_id_eia"].isin(COAL_FORM1_PEER_IDS)].copy()
    if peers.empty:
        print("  WARNING: No coal peer plants found in form1_co — coal proxy skipped")
        return resources, 0

    total_cap = peers["capacity_mw"].sum()
    avg_om_kw = float((peers["non_fuel_om_kw"] * peers["capacity_mw"]).sum() / total_cap)
    avg_cf    = float((peers["actual_cf"]       * peers["capacity_mw"]).sum() / total_cap)

    print(f"\n  Coal peer group (cap-wtd avg):")
    print(f"  {'plant_id_eia':>12}  {'non_fuel $/kW':>14}  {'CF':>6}  {'cap_mw':>8}")
    print(f"  {'-'*48}")
    for _, r in peers.iterrows():
        print(f"  {int(r.plant_id_eia):>12}  {r.non_fuel_om_kw:>14.2f}  {r.actual_cf:>6.3f}  {r.capacity_mw:>8.1f}")
    print(f"  {'wtd average':>12}  {avg_om_kw:>14.2f}  {avg_cf:>6.3f}  {total_cap:>8.1f}")

    atb_yr = (
        atb_lookup[atb_lookup["atb_year"] == ATB_YEAR]
        .set_index("tech_class")[["fixed_om", "variable_om"]]
    )
    fixed_atb     = float(atb_yr.loc["Coal", "fixed_om"])
    vom_atb       = float(atb_yr.loc["Coal", "variable_om"])
    annual_vom_kw = vom_atb * 8760 * avg_cf / 1000
    denom         = fixed_atb + annual_vom_kw
    fixed_share   = fixed_atb / denom if denom > 0 else 1.0

    fixed_rate = round(avg_om_kw * fixed_share, 2)
    en_cost    = round(
        avg_om_kw * (1.0 - fixed_share) / (8760 * avg_cf / 1000) if avg_cf > 0 else 0.0,
        4,
    )
    print(
        f"\n  Proxy rates: FixedRate=${fixed_rate:.2f}/kW-yr, "
        f"EnCost=${en_cost:.4f}/MWh  (fixed_share={fixed_share:.1%} at CF={avg_cf:.3f})"
    )

    matched = 0
    summary = []
    for idx, row in resources.iterrows():
        if pd.notna(row.get("om_source")):
            continue
        if row.get("TechType") != "Coal":
            continue
        if str(row.get("status_category", "")).lower() == "proposed":
            continue

        resources.at[idx, "FixedRate"] = fixed_rate
        resources.at[idx, "EnCost"]    = en_cost
        resources.at[idx, "om_source"] = "form1_co_coal_peer_proxy"
        matched += 1
        summary.append((row["Name"], float(row.get("MaxCap", 0))))

    if summary:
        print(f"\n  Coal peer proxy assignments ({matched} resources):")
        print(f"  {'Name':<50} {'Cap MW':>7}")
        print(f"  {'-'*60}")
        for name, cap in summary:
            print(f"  {name:<50} {cap:>7.1f}")

    return resources, matched


def enrich_atb_fallback(
    resources: pd.DataFrame,
    atb_lookup: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """
    Assigns ATB 2024 Moderate Fixed O&M and Variable O&M to all remaining
    unassigned resources by TechType. Gas:ST and Gas:IC use CT proxy values
    (no dedicated ATB equivalent; see ATB_TECH_SPEC). Proposed and operating
    resources receive the same ATB values (new-build costs for proposed are
    appropriate; ATB Moderate is the standard fallback for existing plants
    without Form 1 coverage).
    """
    atb_yr = (
        atb_lookup[atb_lookup["atb_year"] == ATB_YEAR]
        .set_index("tech_class")[["fixed_om", "variable_om"]]
    )

    matched = 0
    summary = []

    for idx, row in resources.iterrows():
        if pd.notna(row.get("om_source")):
            continue
        tech      = row.get("TechType", "")
        name      = row.get("Name", "")
        tech_lookup = RESOURCE_ATB_OVERRIDES.get(name, tech)
        if tech_lookup not in atb_yr.index:
            print(f"  WARNING: TechType '{tech_lookup}' not in ATB lookup — skipping {name}")
            continue

        fixed_om = float(atb_yr.loc[tech_lookup, "fixed_om"])
        var_om   = float(atb_yr.loc[tech_lookup, "variable_om"])

        resources.at[idx, "FixedRate"] = round(fixed_om, 2)
        resources.at[idx, "EnCost"]    = round(var_om, 4)
        resources.at[idx, "om_source"] = "atb_2024"
        matched += 1
        summary.append((name, tech if tech == tech_lookup else f"{tech}->{tech_lookup}",
                        float(row.get("MaxCap", 0)), fixed_om, var_om))

    if summary:
        print(f"\n  ATB fallback assignments ({matched} resources):")
        print(f"  {'Name':<50} {'Tech':<10} {'Cap':>6} {'$/kW-yr':>9} {'VOM$/MWh':>10}")
        print(f"  {'-'*93}")
        for name, tech, cap, fr, ec in summary:
            print(f"  {name:<50} {tech:<10} {cap:>6.1f} {fr:>9.2f} {ec:>10.4f}")

    return resources, matched


# ---------------------------------------------------------------------------
# Sub-plan E — O&M summary table
# ---------------------------------------------------------------------------

OM_SUMMARY_OUT = (
    DATA_CLEANING / "resources" / "costs" / "om_summary_plants.txt"
)
OM_SUMMARY_OUT_2 = (
    DATA_CLEANING / "resources" / "costs" / "om_summary_proxies.txt"
)

# plant_id_eia → paper-ready display name
# Used to label plant-level rows aggregated across individual unit resources.
FORM1_PLANT_DISPLAY: dict[int, str] = {
    464:   "Alamosa",
    467:   "Cabin Creek",
    469:   "Cherokee",
    470:   "Comanche",
    471:   "Fruita",
    525:   "Hayden",
    6021:  "Craig",
    6112:  "Fort St. Vrain",
    6248:  "Pawnee",
    8067:  "Fort Lupton",
    55127: "Manchief",
    55207: "Valmont",
    55645: "Blue Spruce",
    55835: "Rocky Mountain",
    56998: "Pueblo Airport",
}

# Non-Form-1 existing plants with notable individual assignments
NOTABLE_NONFORN1_DISPLAY: dict[str, str] = {
    "rawhide__1":    "Rawhide",
    "ray_d_nixon__1": "Ray D. Nixon",
    "pawnee__1":     "Pawnee",
}

# Form 1 Schedule 410 wind plants — shown individually in the table
# even though the model aggregates them with LBNL-proxied plants in each group
FORM1_WIND_DISPLAY: dict[int, str] = {
    57980: "Busch Ranch",
    60143: "Peak View",
    60619: "Rush Creek Wind",
    62952: "Cheyenne Ridge",
}


def build_om_summary_table(
    resources: pd.DataFrame,
    form1_co: pd.DataFrame,
    form1_wind: pd.DataFrame,
    atb_lookup: pd.DataFrame,
    extra_form1_totals: dict[int, float] | None = None,
) -> pd.DataFrame:
    """
    Build a tab-delimited summary table of O&M parameters for the methods section.
    Sections:
      A  Named existing thermal plants (Form 1 S402 and coal peer proxy)
      B  Named existing gas plants without Form 1 (ATB proxy, notable units only)
      C  Named existing hydro plants (Form 1 S408 and ORNL proxies)
      D  Form 1 Schedule 410 wind plants (individual, pre-aggregation)
      E  Technology proxy benchmarks (ATB, LBNL, ORNL)

    Saved as tab-delimited text to OM_SUMMARY_OUT for direct Word import.
    """
    # ---- helpers ----
    f1_total   = form1_co.set_index("plant_id_eia")["non_fuel_om_kw"].to_dict()
    if extra_form1_totals:
        f1_total.update(extra_form1_totals)
    atb24      = atb_lookup[atb_lookup["atb_year"] == ATB_YEAR].set_index("tech_class")
    f1w        = form1_wind.set_index("plant_id_eia")

    col_order_t1 = [
        "Plant / Benchmark", "Technology",
        "Capacity (MW)",
        "Fixed O&M ($/kW-yr)", "Variable O&M ($/MWh)",
    ]
    col_order_t2 = [
        "Plant / Benchmark", "Technology",
        "Fixed O&M ($/kW-yr)", "Variable O&M ($/MWh)",
        "Source",
    ]

    def make_row(section, name, tech, cap, source, total, fixed, var, notes=""):
        return {
            "Plant / Benchmark":    name,
            "Technology":           tech,
            "Capacity (MW)":        f"{cap:.0f}" if cap is not None else "",
            "Fixed O&M ($/kW-yr)": f"{fixed:.2f}" if fixed is not None else "",
            "Variable O&M ($/MWh)": f"{var:.2f}" if var is not None else "",
            "Source":               source,
        }

    # ---- aggregate individual unit resources to plant level ----
    # Group by (plant_id_eia, TechType, om_source); sum caps; values identical within group.
    plant_groups: dict[tuple, dict] = {}
    for _, r in resources.iterrows():
        raw = r.get("plant_codes")
        if pd.isna(raw) or pd.isna(r.get("om_source")):
            continue
        codes = [int(c.strip()) for c in str(raw).split(";") if c.strip()]
        if len(codes) != 1:
            continue   # grouped multi-plant resources handled elsewhere
        pid  = codes[0]
        tech = r.get("TechType", "")
        src  = r.get("om_source", "")
        key  = (pid, tech, src)
        if key not in plant_groups:
            plant_groups[key] = {
                "pid": pid, "tech": tech, "source": src,
                "cap": 0.0,
                "fixed": float(r["FixedRate"]),
                "var":   float(r["EnCost"]),
                "name":  r.get("Name", ""),
                "status": str(r.get("status_category", "")).lower(),
            }
        plant_groups[key]["cap"] += float(r.get("MaxCap", 0))

    rows_t1 = []   # individual plant rows (Table 1)
    rows_t2 = []   # generic proxy rows (Table 2)

    # ---- Section A: thermal plants with Form 1 or peer proxy ----
    form1_src   = {"form1_2021_2023"}
    proxy_src   = {"form1_co_coal_peer_proxy"}
    form1_notes = {
        6112: "Blended rate across CC (unit 1) and CT (units 2-6) at same EIA plant code",
        469:  "Blended rate across Gas:CC (unit 7), Gas:CT (units 5-6), Gas:ST (unit 4)",
        55835:"Blended rate across CC (STG1) and CT (CTG1-2) at same EIA plant code",
        470:  "2023 only; excludes Unit 1 retired 2022",
    }
    proxy_note = "Cap-wtd avg of Comanche, Hayden, Craig Form 1 totals"

    for key, g in sorted(plant_groups.items(), key=lambda x: (x[1]["tech"], -x[1]["cap"])):
        pid, tech, src = key
        if g["status"] == "proposed":
            continue
        if g["cap"] < 50:
            continue
        if tech in {"Wind", "Solar:PV", "Storage:Battery", "Hydro", "Hydro:Pumped"}:
            continue
        if src not in form1_src | proxy_src:
            continue
        if pid not in FORM1_PLANT_DISPLAY and g["name"] not in NOTABLE_NONFORN1_DISPLAY:
            continue

        display = FORM1_PLANT_DISPLAY.get(pid, NOTABLE_NONFORN1_DISPLAY.get(g["name"], g["name"]))

        total = f1_total.get(pid) if src in form1_src else 43.59
        source_label = (
            "FERC Form 1 S402 (3-yr avg, 2021–23)" if src in form1_src
            else "CO Form 1 coal peer proxy"
        )
        note = proxy_note if src in proxy_src else form1_notes.get(pid, "")

        rows_t1.append(make_row(
            "A. Thermal — Form 1 / peer proxy",
            display, tech, g["cap"], source_label,
            total, g["fixed"], g["var"], note,
        ))

    # ---- Section B: notable existing gas plants without Form 1 (ATB-assigned) ----
    for rname, display in NOTABLE_NONFORN1_DISPLAY.items():
        match = resources[resources["Name"] == rname]
        if match.empty:
            continue
        r = match.iloc[0]
        if r.get("om_source") not in {"atb_2024"}:
            continue
        tech = r.get("TechType", "")
        rows_t1.append(make_row(
            "B. Notable gas plants — ATB proxy",
            display, tech, float(r["MaxCap"]),
            "ATB",
            None, float(r["FixedRate"]), float(r["EnCost"]),
            "Post-coal conversion (late 2025); CC ATB proxy used for Gas:ST" if rname == "pawnee__1" else "",
        ))

    # ---- Section C: hydro plants ----
    # Cabin Creek (Form 1 Schedule 408)
    cc = resources[resources["om_source"] == "form1_hydro_2024_2025"]
    if not cc.empty:
        total_cap = cc["MaxCap"].sum()
        r0 = cc.iloc[0]
        rows_t1.append(make_row(
            "C. Hydro — Form 1 / ORNL",
            "Cabin Creek", "Hydro:Pumped",
            total_cap,
            "FERC Form 1 S408 (2024–25 post-upgrade)",
            None, float(r0["FixedRate"]), float(r0["EnCost"]),
            "2018–24 upgrade outage; 2024-25 used only",
        ))
    # Federal PSH (ORNL)
    fed_psh = resources[
        (resources["om_source"] == "ornl_ferc1_median")
        & (resources["TechType"] == "Hydro:Pumped")
    ]
    if not fed_psh.empty:
        rows_t1.append(make_row(
            "C. Hydro — Form 1 / ORNL",
            "Mt. Elbert / Flatiron",
            "Hydro:Pumped",
            fed_psh["MaxCap"].sum(),
            "ORNL/TM-2021/2297 PSH median (2025$)",
            None,
            float(fed_psh.iloc[0]["FixedRate"]),
            float(fed_psh.iloc[0]["EnCost"]),
            "WAPA / Bureau of Reclamation; exempt from FERC Form 1",
        ))
    # Conventional hydro groups (ORNL)
    conv_hydro = resources[
        (resources["om_source"] == "ornl_ferc1_median")
        & (resources["TechType"] == "Hydro")
        & (resources["MaxCap"] >= 50)
    ]
    for _, r in conv_hydro.iterrows():
        rows_t1.append(make_row(
            "C. Hydro — Form 1 / ORNL",
            r["Name"].replace("_", " "), "Hydro",
            float(r["MaxCap"]),
            "ORNL/TM-2021/2297 size class (2025$)",
            None, float(r["FixedRate"]), float(r["EnCost"]),
            "Publicly owned; grouped resource",
        ))

    # ---- Section D: Form 1 Schedule 410 wind plants (individual) ----
    for pid, display in sorted(FORM1_WIND_DISPLAY.items(), key=lambda x: -f1w.loc[x[0], "capacity_mw"] if x[0] in f1w.index else 0):
        if pid not in f1w.index:
            continue
        wr = f1w.loc[pid]
        note = "2021–22 only; 2023 partial retirement excluded" if pid == 57980 else ""
        rows_t1.append(make_row(
            "D. Wind — Form 1 S410 (individual plants)",
            display, "Wind",
            float(wr["capacity_mw"]),
            "FERC Form 1 S410 (2021–23 avg)",
            float(wr["om_kw"]),
            float(wr["om_kw"]), 0.0,
            note,
        ))

    # ---- Section E: technology proxy benchmarks (Table 2) ----
    # ATB Moderate
    atb_proxies = [
        ("Gas:CC",          "Gas Combined Cycle"),
        ("Gas:CT",          "Gas Combustion Turbine"),
        ("Gas:ST",          "Gas Steam Turbine"),
        ("Storage:Battery", "Battery Storage (4-hr)"),
    ]
    for tech, label in atb_proxies:
        if tech not in atb24.index:
            continue
        ar = atb24.loc[tech]
        rows_t2.append(make_row(
            "E. Technology proxies",
            label, tech, None,
            "ATB",
            None, float(ar["fixed_om"]), float(ar["variable_om"]),
        ))
    # LBNL wind vintages
    for vintage, om in [("Pre-2010", 20.0), ("2010–2019", 21.0), ("2020+", 18.0)]:
        rows_t2.append(make_row(
            "E. Technology proxies",
            f"Wind {vintage}", "Wind", None,
            "LBNL",
            None, om, 0.0,
        ))
    # LBNL solar
    rows_t2.append(make_row("E. Technology proxies", "Solar PV, operating", "Solar:PV", None,
                            "LBNL", None, LBNL_SOLAR_OM_OPERATING, 0.0))
    rows_t2.append(make_row("E. Technology proxies", "Solar PV, proposed", "Solar:PV", None,
                            "LBNL", None, LBNL_SOLAR_OM_PROPOSED, 0.0))
    # ORNL hydro size classes
    ornl_classes = [
        ("<10 MW",    126.0),
        ("10–30 MW",   58.0),
        ("30–100 MW",  34.0),
        (">100 MW",    23.0),
    ]
    for label, median_2020 in ornl_classes:
        fixed_2025 = round(median_2020 * ORNL_HYDRO_CPI_FACTOR, 2)
        rows_t2.append(make_row(
            "E. Technology proxies",
            f"Hydro {label}", "Hydro", None,
            "ORNL",
            None, fixed_2025, 0.0,
        ))

    df1 = pd.DataFrame(rows_t1, columns=col_order_t1).rename(columns={"Plant / Benchmark": "Plant"})
    df2 = pd.DataFrame(rows_t2, columns=col_order_t2).rename(columns={"Plant / Benchmark": "Benchmark"})

    OM_SUMMARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    df1.to_csv(OM_SUMMARY_OUT,   index=False, sep="\t")
    df2.to_csv(OM_SUMMARY_OUT_2, index=False, sep="\t")

    # Console summary — Table 1
    print(f"\n  Table 1: Individual plants")
    print(f"  {'Plant':<40} {'Tech':<16} {'Cap':>5} {'Fixed$/kW':>9} {'VOM$/MWh':>9}")
    print(f"  {'-'*84}")
    for _, r in df1.iterrows():
        cap_s   = r["Capacity (MW)"]        or "  —"
        fixed_s = r["Fixed O&M ($/kW-yr)"]  or "  —"
        var_s   = r["Variable O&M ($/MWh)"] or "  —"
        print(f"  {r['Plant']:<40} {r['Technology']:<16} "
              f"{cap_s:>5} {fixed_s:>9} {var_s:>9}")

    # Console summary — Table 2
    print(f"\n  Table 2: Generic proxies")
    print(f"  {'Benchmark':<30} {'Tech':<16} {'Fixed$/kW':>9} {'VOM$/MWh':>9}  Source")
    print(f"  {'-'*84}")
    for _, r in df2.iterrows():
        fixed_s = r["Fixed O&M ($/kW-yr)"]  or "  —"
        var_s   = r["Variable O&M ($/MWh)"] or "  —"
        print(f"  {r['Benchmark']:<30} {r['Technology']:<16} "
              f"{fixed_s:>9} {var_s:>9}  {r['Source']}")

    return df1, df2


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Build O&M costs for existing resources.")
    parser.add_argument(
        "--redownload", action="store_true",
        help="Force a fresh ATB download even if a cached copy already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print("\n--- Script 16A: ATB O&M Data ---")

    atb_raw = load_atb_raw(download_atb(force=args.redownload))
    lookup  = build_atb_om_lookup(atb_raw)

    ATB_OUT.parent.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(ATB_OUT, index=False)
    print(f"\n  Saved: {ATB_OUT.name}  ({len(lookup)} rows)")

    # Print current-year (2024) values for spot-check
    cur = (
        lookup[lookup["atb_year"] == ATB_YEAR]
        [["tech_class", "fixed_om", "variable_om", "ref_cf", "fixed_share"]]
        .set_index("tech_class")
    )
    print(f"\n  ATB {ATB_YEAR} O&M (Moderate scenario):")
    print(f"  {'Tech':<20} {'Fixed $/kW-yr':>14} {'VOM $/MWh':>10} {'Ref CF':>7} {'Fixed%':>7}")
    print(f"  {'-'*60}")
    for tech, row in cur.iterrows():
        print(
            f"  {tech:<20} {row['fixed_om']:>14,.2f} {row['variable_om']:>10.4f}"
            f" {row['ref_cf']:>7.0%} {row['fixed_share']:>7.1%}"
        )

    print("\n--- Script 16B1: Form 1 O&M for Named CO Thermal Plants ---")

    form1 = build_form1_co_extract(FORM1_RAW_CSV)
    FORM1_OUT.parent.mkdir(parents=True, exist_ok=True)
    form1.to_csv(FORM1_OUT, index=False)
    print(f"\n  Saved: {FORM1_OUT.name}  ({len(form1)} plants)")

    resources = pd.read_csv(RESOURCES_CSV)
    # Reset enrichment columns once at the start of all B-series passes
    for col in ["FixedRate", "EnCost", "om_source"]:
        resources[col] = None

    resources = enrich_with_form1(resources, form1, lookup)
    resources.to_csv(RESOURCES_CSV, index=False)

    print("\n--- Script 16B2: Form 1 O&M for Hydro (Cabin Creek) + ATB fallback ---")

    form1_hydro = build_form1_hydro_extract()
    FORM1_HYDRO_OUT.parent.mkdir(parents=True, exist_ok=True)
    form1_hydro.to_csv(FORM1_HYDRO_OUT, index=False)
    print(f"\n  Saved: {FORM1_HYDRO_OUT.name}  ({len(form1_hydro)} plants)")

    resources = pd.read_csv(RESOURCES_CSV)
    resources = enrich_with_form1(
        resources, form1_hydro, lookup, om_source_label="form1_hydro_2024_2025"
    )

    resources, _ = enrich_hydro_atb_fallback(resources, lookup)

    resources.to_csv(RESOURCES_CSV, index=False)
    n_remaining = int(resources["om_source"].isna().sum())
    print(f"\n  Updated: {RESOURCES_CSV.name}  ({n_remaining} resources still unassigned)")

    print("\n--- Script 16C: Wind, Solar, Battery O&M ---")

    gen_df = pd.read_csv(GENERATORS_CSV)
    gen_df["commission_year"] = pd.to_datetime(
        gen_df["commission_date"], errors="coerce"
    ).dt.year
    wind_gen = gen_df[gen_df["tech_type"] == "Wind"].copy()

    form1_wind = build_form1_wind_extract()
    plant_rates = build_wind_plant_rates(form1_wind, wind_gen)
    FORM1_WIND_OUT.parent.mkdir(parents=True, exist_ok=True)
    plant_rates.to_csv(FORM1_WIND_OUT, index=False)
    print(f"\n  Saved: {FORM1_WIND_OUT.name}  ({len(plant_rates)} plants)")

    resources = pd.read_csv(RESOURCES_CSV)
    resources, n = enrich_wind_all(resources, plant_rates, wind_gen)
    print(f"\n  C1 Wind (Form 1 + LBNL blend): {n} resources assigned")
    resources, n = enrich_solar_lbnl(resources)
    print(f"  C2 LBNL solar:                 {n} resources assigned")
    resources, n = enrich_battery_atb(resources, lookup)
    print(f"  C3 ATB battery:                {n} resources assigned")

    resources.to_csv(RESOURCES_CSV, index=False)
    n_remaining = int(resources["om_source"].isna().sum())
    print(f"\n  Updated: {RESOURCES_CSV.name}  ({n_remaining} resources still unassigned)")

    print("\n--- Script 16D: Pueblo Airport CC Form 1 + ATB Thermal Fallback ---")

    resources = pd.read_csv(RESOURCES_CSV)

    # Pueblo Airport CC (plant 56998): Form 1 S402, Black Hills CO Electric (utility 309).
    # allowed_tech_types restricts to Gas:CC only — the GT units at the same plant code
    # are combustion turbines not covered by Schedule 402 and receive ATB below.
    form1_pa = build_form1_pueblo_airport_cc()
    if not form1_pa.empty:
        resources = enrich_with_form1(
            resources, form1_pa, lookup,
            om_source_label="form1_2021_2023",
            allowed_tech_types={"Gas:CC"},
        )

    resources, n_coal = enrich_coal_peer_proxy(resources, form1, lookup)
    print(f"\n  D2 Coal peer proxy: {n_coal} resources assigned")

    resources, n_atb = enrich_atb_fallback(resources, lookup)
    print(f"\n  D3 ATB fallback: {n_atb} resources assigned")

    resources.to_csv(RESOURCES_CSV, index=False)
    n_remaining = int(resources["om_source"].isna().sum())
    print(f"\n  Updated: {RESOURCES_CSV.name}  ({n_remaining} resources still unassigned)")

    print("\n--- Script 16E: O&M Summary Table ---")

    resources  = pd.read_csv(RESOURCES_CSV)
    form1_wind = pd.read_csv(FORM1_WIND_OUT)
    # Pass Pueblo Airport CC total (extracted in D, not in form1_co_om.csv)
    pa_total = (
        {56998: float(form1_pa.iloc[0]["non_fuel_om_kw"])}
        if not form1_pa.empty else {}
    )
    build_om_summary_table(resources, form1, form1_wind, lookup, extra_form1_totals=pa_total)
    print(f"\n  Saved: {OM_SUMMARY_OUT.name}")
    print(f"  Saved: {OM_SUMMARY_OUT_2.name}")


if __name__ == "__main__":
    main()
