"""
Script 15: Heat Rates and Emission Rates

Enriches colorado_resources.csv (Script 14 output) with heat rates and emission rates
using eGRID2023 PLNT23 plant-level data (primary) or technology-class proxies (fallback).

Routing (checked in order for each resource):
  1. Proposed resources                  -> proxy by tech_type
  2. Zero-emission techs                 -> NaN heat rate, zero emissions
  3. Large CC CA (is_grouped=False, pm=CA) -> proxy "Gas:CC_ca" (waste-heat conversion)
  4. Large CC CT (waste_heat_resource set) -> proxy "Gas:CT_cc" (simple-cycle rate)
  5. All remaining thermal               -> eGRID PLNT23 -> proxy fallback

Sources:
  Heat rates: EIA Electric Power Annual Table 8.1 (proxies); eGRID PLNT23 (actual)
  CO2: EPA "Emission Factors for GHG Inventories" 2024 (117 lbs CO2/MMBtu for gas)
  NOx/SO2: EPA AP-42 Ch 1.1, 3.1, 3.2 (proxies); eGRID PLNT23 (actual)

New columns added (6):
  AvgHtRate, heat_rate_source,
  co2_RelRateMWh, nox_RelRateMWh, so2_RelRateMWh, emission_source
"""

import argparse
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT  = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"
RESOURCES_CSV = DATA_CLEANING / "resources" / "colorado_resources.csv"
EGRID_CACHE   = DATA_CLEANING / "resources" / "egrid" / "raw" / "egrid2023_data_rev2.xlsx"

EGRID_URL = "https://www.epa.gov/system/files/documents/2025-06/egrid2023_data_rev2.xlsx"
PLNT_TAB  = "PLNT23"
UNT_TAB   = "UNT23"
GEN_TAB   = "GEN23"

CF_CUTOFF    = 0.05     # PLCAPFAC below this -> reject eGRID, use proxy
NETGEN_FLOOR = 1_000.0  # MWh; annual net gen below this -> reject eGRID, use proxy

# Plants where eGRID data is known stale or inapplicable — skip directly to proxy.
# Pawnee (6248): converted from coal to gas in 2025; eGRID 2023 reflects coal operations.
EGRID_PROXY_OVERRIDE: set[int] = {6248}

THERMAL_TECHS       = {"Coal", "Gas:CC", "Gas:CT", "Gas:ST", "Gas:IC", "Nuclear", "Other"}
ZERO_EMISSION_TECHS = {"Wind", "Solar:PV", "Solar:CSP", "Hydro", "Hydro:Pumped", "Storage:Battery"}

# Proxy defaults: EIA EPA 2022 + EPA emission factor tables (see plan for citations)
PROXY_DEFAULTS: dict[str, dict] = {
    "Coal":      {"heat_rate": 10300, "co2": 2110, "nox": 1.5,  "so2":  0.90},  # NOx: capacity-weighted avg of measured CO coal fleet (CEMS); SO2: AP-42 Ch.1.1, 0.4% S PRB coal, 90% FGD
    "Gas:CC":    {"heat_rate":  7600, "co2":  890, "nox": 0.3,  "so2":  0.02},  # NOx: measured CO CC fleet avg (DLN combustors); full combined block
    "Gas:CC_ca": {"heat_rate":     0, "co2":    0, "nox": 0.0,  "so2":  0.00},  # unused — CA routed to not_applicable
    "Gas:CT_cc": {"heat_rate": 10500, "co2": 1230, "nox": 0.5,  "so2":  0.03},  # CC-coupled CT; NOx consistent with Gas:CT
    "Gas:CT":    {"heat_rate": 10800, "co2": 1260, "nox": 0.5,  "so2":  0.03},  # NOx: measured CO standalone CT fleet avg ~0.35; rounded up slightly
    "Gas:ST":    {"heat_rate": 13500, "co2": 1580, "nox": 0.7,  "so2":  0.10},  # NOx: Cherokee Gas:ST measured at 0.71 lb/MWh (CEMS)
    "Gas:IC":    {"heat_rate":  9500, "co2": 1110, "nox": 3.0,  "so2":  0.03},
    "Nuclear":   {"heat_rate": 10500, "co2":    0, "nox": 0.0,  "so2":  0.00},
    "Other":     {"heat_rate": 12000, "co2": 1200, "nox": 2.0,  "so2":  1.00},
}

SANITY_BOUNDS: dict[str, tuple[float, float]] = {
    "Coal":   ( 8_000, 15_000),
    "Gas:CC": ( 5_500, 10_000),
    "Gas:CT": ( 8_500, 18_000),  # floor raised: 7,000 passes CC-contaminated plant rates for co-located GTs
    "Gas:ST": ( 8_000, 20_000),
    "Gas:IC": ( 6_000, 14_000),
    "Nuclear":( 8_000, 12_000),
}

# eGRID PLNT23 column names (verified at runtime by _verify_columns)
_PCOL = {
    "id":      "ORISPL",
    "netgen":  "PLNGENAN",
    "heatrate":"PLHTRT",
    "capfac":  "CAPFAC",
    "co2":     "PLCO2RTA",
    "nox":     "PLNOXRTA",
    "so2":     "PLSO2RTA",
    "namecap": "NAMEPCAP",
    "primfuel":"PLPRMFL",
}

# PLNT23 primary fuel codes that indicate coal — gas-tech resources matched to
# these plants get proxy emissions instead of plant-level rates (which are
# dominated by coal combustion and give wildly wrong CO2/SO2 for a gas CT/ST).
_COAL_FUELS: frozenset[str] = frozenset({"SUB", "BIT", "LIG", "ANT", "RC", "SC", "WC"})

# eGRID UNT23 / GEN23 column names for unit-level heat rate calculation
# Heat rate = UNT.HTIAN (MMBtu) × 1000 / GEN.GENNTAN (MWh)  →  BTU/kWh
# Emissions = UNT.{CO2,NOx,SO2}AN (short tons) × 2000 / GEN.GENNTAN  →  lbs/MWh
# Only used when NUMGEN==1 (unit feeds 1 generator) AND NUMBLR==1 (generator fed by 1 unit)
# AND UNITID == GENID (IDs match, confirming unambiguous 1:1 pairing)
_UCOL = {
    "plant_id": "ORISPL",
    "unit_id":  "UNITID",
    "numgen":   "NUMGEN",   # generators per unit; must be 1
    "heat_in":  "HTIAN",    # annual heat input (MMBtu)
    "co2":      "CO2AN",    # annual CO2 (short tons)
    "nox":      "NOXAN",    # annual NOx (short tons)
    "so2":      "SO2AN",    # annual SO2 (short tons)
}
_GCOL = {
    "plant_id": "ORISPL",
    "gen_id":   "GENID",
    "numblr":   "NUMBLR",   # boilers/units per generator; must be 1
    "netgen":   "GENNTAN",  # annual net generation (MWh)
    "capfac":   "CFACT",    # capacity factor
}

# Plants where UNT23 unit IDs differ from GEN23 generator IDs by a known prefix.
# Maps {orispl: {unit_id_in_UNT23: gen_id_in_GEN23}} so the lookup key matches
# what our CSV stores in generator_ids (which comes from EIA-860 GEN IDs).
_UNIT_ID_REMAP: dict[int, dict[str, str]] = {
    55835: {"1": "CTG1", "2": "CTG2"},  # Rocky Mountain Energy Center
}

NEW_COLS = [
    "AvgHtRate", "heat_rate_source",
    "co2_RelRateMWh", "nox_RelRateMWh", "so2_RelRateMWh", "emission_source",
]


# ---------------------------------------------------------------------------
# eGRID loading
# ---------------------------------------------------------------------------

def download_egrid(force: bool = False) -> Path:
    if EGRID_CACHE.exists() and not force:
        size_mb = EGRID_CACHE.stat().st_size / 1_048_576
        print(f"  eGRID cached ({size_mb:.1f} MB): {EGRID_CACHE.name}")
        return EGRID_CACHE
    EGRID_CACHE.parent.mkdir(parents=True, exist_ok=True)
    print("  Downloading eGRID 2023 from EPA (this may take a minute)...")
    urllib.request.urlretrieve(EGRID_URL, EGRID_CACHE)
    size_mb = EGRID_CACHE.stat().st_size / 1_048_576
    print(f"  Saved ({size_mb:.1f} MB): {EGRID_CACHE}")
    return EGRID_CACHE


def _verify_columns(df: pd.DataFrame, required: list[str], tab_name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        avail = sorted(df.columns.tolist())
        raise ValueError(
            f"eGRID {tab_name} missing expected columns: {missing}\n"
            f"Columns actually present: {avail}"
        )


def load_egrid_plnt(xlsx_path: Path) -> pd.DataFrame:
    """Load PLNT23; coerce numeric columns; index on ORISPL (int)."""
    print(f"  Loading {PLNT_TAB} from eGRID...")
    raw = pd.read_excel(xlsx_path, sheet_name=PLNT_TAB, header=1)
    _verify_columns(raw, list(_PCOL.values()), PLNT_TAB)
    numeric_cols = [_PCOL["netgen"], _PCOL["heatrate"], _PCOL["capfac"],
                    _PCOL["co2"], _PCOL["nox"], _PCOL["so2"], _PCOL["namecap"]]
    # primfuel (PLPRMFL) is a string code — do not coerce to numeric
    for col in numeric_cols:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw[_PCOL["id"]] = pd.to_numeric(raw[_PCOL["id"]], errors="coerce")
    plnt = raw.dropna(subset=[_PCOL["id"]]).copy()
    plnt[_PCOL["id"]] = plnt[_PCOL["id"]].astype(int)
    plnt = plnt.set_index(_PCOL["id"])
    print(f"  {len(plnt):,} plants indexed")
    return plnt


def build_unit_gen_lookup(xlsx_path: Path) -> dict[tuple, dict]:
    """Build {(orispl_int, gen_id_str): rates_dict} for unambiguous 1:1 unit-generator pairs.

    Rates are calculated directly from annual totals:
      heat_rate (BTU/kWh) = UNT.HTIAN_MMBtu × 1000 / GEN.GENNTAN_MWh
      emissions (lbs/MWh) = UNT.{CO2,NOx,SO2}AN_tons × 2000 / GEN.GENNTAN_MWh

    A pair qualifies only when:
      - UNITID == GENID  (IDs match → unambiguous pairing)
      - UNT.NUMGEN == 1  (unit feeds exactly one generator)
      - GEN.NUMBLR == 1  (generator fed by exactly one unit)
      - GEN.GENNTAN >= NETGEN_FLOOR  (adequate annual output)
    """
    print(f"  Loading {UNT_TAB} and {GEN_TAB} from eGRID for unit-level rates...")
    unt = pd.read_excel(xlsx_path, sheet_name=UNT_TAB, header=1)
    gen = pd.read_excel(xlsx_path, sheet_name=GEN_TAB, header=1)

    for col in [_UCOL["numgen"], _UCOL["heat_in"], _UCOL["co2"], _UCOL["nox"], _UCOL["so2"]]:
        unt[col] = pd.to_numeric(unt[col], errors="coerce")
    for col in [_GCOL["numblr"], _GCOL["netgen"], _GCOL["capfac"]]:
        gen[col] = pd.to_numeric(gen[col], errors="coerce")
    unt[_UCOL["plant_id"]] = pd.to_numeric(unt[_UCOL["plant_id"]], errors="coerce")
    gen[_GCOL["plant_id"]] = pd.to_numeric(gen[_GCOL["plant_id"]], errors="coerce")

    # Keep only 1:1 records
    # NUMGEN: NaN is common for CT units in CC plants (eGRID gap, not genuine ambiguity);
    #   exclude only NUMGEN>1 (unit confirmed to serve multiple generators)
    # NUMBLR: NaN is normal for CT/GT generators (no boiler);
    #   exclude only NUMBLR>1 (CA/ST generators fed by multiple units)
    # Primary guard against incorrect pairing is UNITID==GENID (enforced at intersection step)
    unt = unt[unt[_UCOL["numgen"]].isna() | (unt[_UCOL["numgen"]] == 1)].dropna(subset=[_UCOL["plant_id"]]).copy()
    gen = gen[gen[_GCOL["numblr"]].isna() | (gen[_GCOL["numblr"]] == 1)].dropna(subset=[_GCOL["plant_id"]]).copy()

    # Build plain dicts keyed by (plant_int, id_str) to avoid pandas tuple-index ambiguity
    unt_d: dict[tuple, pd.Series] = {}
    for _, r in unt.iterrows():
        plant_int = int(r[_UCOL["plant_id"]])
        raw_uid   = str(r[_UCOL["unit_id"]]).strip()
        mapped_id = _UNIT_ID_REMAP.get(plant_int, {}).get(raw_uid, raw_uid)
        key = (plant_int, mapped_id)
        if key not in unt_d:
            unt_d[key] = r

    gen_d: dict[tuple, pd.Series] = {}
    for _, r in gen.iterrows():
        key = (int(r[_GCOL["plant_id"]]), str(r[_GCOL["gen_id"]]).strip())
        if key not in gen_d:
            gen_d[key] = r

    lookup: dict[tuple, dict] = {}
    for key in set(unt_d.keys()) & set(gen_d.keys()):
        ur = unt_d[key]
        gr = gen_d[key]

        net_mwh = float(gr[_GCOL["netgen"]]) if pd.notna(gr[_GCOL["netgen"]]) else 0.0
        heat_in = float(ur[_UCOL["heat_in"]]) if pd.notna(ur[_UCOL["heat_in"]]) else 0.0
        capfac  = float(gr[_GCOL["capfac"]])  if pd.notna(gr[_GCOL["capfac"]])  else 0.0

        if net_mwh < NETGEN_FLOOR or heat_in <= 0 or capfac < CF_CUTOFF:
            continue

        lookup[key] = {
            "heat_rate": heat_in * 1_000.0 / net_mwh,
            "co2": float(ur[_UCOL["co2"]]) * 2_000.0 / net_mwh if pd.notna(ur[_UCOL["co2"]]) else float("nan"),
            "nox": float(ur[_UCOL["nox"]]) * 2_000.0 / net_mwh if pd.notna(ur[_UCOL["nox"]]) else float("nan"),
            "so2": float(ur[_UCOL["so2"]]) * 2_000.0 / net_mwh if pd.notna(ur[_UCOL["so2"]]) else float("nan"),
        }

    print(f"  Unit-level lookup: {len(lookup):,} generator entries")
    return lookup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_codes(s) -> list[int]:
    """'469; 6112' -> [469, 6112]"""
    if pd.isna(s) or str(s).strip() == "":
        return []
    return [int(x.strip()) for x in str(s).split(";") if x.strip().lstrip("-").isdigit()]


def _passes_cutoff(capfac, netgen) -> bool:
    if pd.isna(capfac) or pd.isna(netgen):
        return False
    return float(capfac) >= CF_CUTOFF and float(netgen) >= NETGEN_FLOOR


def _passes_sanity(heat_rate: float, tech_type: str) -> bool:
    if tech_type not in SANITY_BOUNDS:
        return True
    lo, hi = SANITY_BOUNDS[tech_type]
    return lo <= heat_rate <= hi


def _plant_row(code: int, plnt: pd.DataFrame) -> pd.Series | None:
    if code not in plnt.index:
        return None
    return plnt.loc[code]


def _apply_proxy(proxy_key: str) -> dict:
    p = PROXY_DEFAULTS[proxy_key]
    is_cc_component = proxy_key in {"Gas:CC_ca", "Gas:CT_cc"}
    return {
        "AvgHtRate":         float(p["heat_rate"]),
        "heat_rate_source":  "proxy_cc_component" if is_cc_component else "proxy_tech_class",
        "co2_RelRateMWh":    float(p["co2"]),
        "nox_RelRateMWh":    float(p["nox"]),
        "so2_RelRateMWh":    float(p["so2"]),
        "emission_source":   (
            "zero_direct_emission" if proxy_key == "Gas:CC_ca"
            else "proxy_cc_component" if is_cc_component
            else "proxy_fuel_factor"
        ),
    }


def _zero_emission() -> dict:
    return {
        "AvgHtRate":         float("nan"),
        "heat_rate_source":  "not_applicable",
        "co2_RelRateMWh":    0.0,
        "nox_RelRateMWh":    0.0,
        "so2_RelRateMWh":    0.0,
        "emission_source":   "zero_emission",
    }


# ---------------------------------------------------------------------------
# eGRID enrichment
# ---------------------------------------------------------------------------

def _enrich_egrid(row: pd.Series, plnt: pd.DataFrame,
                  unt_gen_lk: dict) -> dict:
    """Enrich a thermal resource from eGRID; proxy fallback if data fails.

    Individual resources: try unit-level (UNT23/GEN23) first, then plant-level (PLNT23).
    Grouped resources: plant-level MW-weighted average only.
    """
    tech  = row["TechType"]
    codes = parse_codes(row["plant_codes"])
    proxy = _apply_proxy(tech if tech in PROXY_DEFAULTS else "Other")

    if not row["is_grouped"]:
        # Individual: single plant_code join
        if len(codes) != 1:
            return proxy
        plant_code = codes[0]

        # Skip eGRID entirely for plants with known stale data
        if plant_code in EGRID_PROXY_OVERRIDE:
            return proxy

        gen_id = str(row["generator_ids"]).strip()

        # 1. Try unit-level lookup (unambiguous 1:1 pairing only)
        ug = unt_gen_lk.get((plant_code, gen_id))
        if ug is not None and _passes_sanity(ug["heat_rate"], tech):
            return {
                "AvgHtRate":         ug["heat_rate"],
                "heat_rate_source":  "egrid_unit",
                "co2_RelRateMWh":    ug["co2"],
                "nox_RelRateMWh":    ug["nox"],
                "so2_RelRateMWh":    ug["so2"],
                "emission_source":   "egrid_unit",
            }

        # 2. Fall back to plant-level PLNT23
        prow = _plant_row(plant_code, plnt)
        if prow is None:
            return proxy
        hr = prow[_PCOL["heatrate"]]
        if pd.isna(hr) or not _passes_cutoff(prow[_PCOL["capfac"]], prow[_PCOL["netgen"]]):
            return proxy
        if not _passes_sanity(hr, tech):
            return proxy
        # If a gas tech is co-located at a coal-primary plant, the entire PLNT23
        # record is coal-dominated — heat rate and emissions are both wrong for
        # the gas unit. Fall through to full proxy.
        plant_fuel = str(prow[_PCOL["primfuel"]]).strip().upper()
        gas_tech = tech in ("Gas:CT", "Gas:ST", "Gas:IC", "Gas:CC")
        if gas_tech and plant_fuel in _COAL_FUELS:
            return proxy
        return {
            "AvgHtRate":         float(hr),
            "heat_rate_source":  "egrid_plant",
            "co2_RelRateMWh":    float(prow[_PCOL["co2"]]),
            "nox_RelRateMWh":    float(prow[_PCOL["nox"]]),
            "so2_RelRateMWh":    float(prow[_PCOL["so2"]]),
            "emission_source":   "egrid_plant",
        }

    else:
        # Grouped: MW-weighted PLNT23 average across plant_codes
        if not codes:
            return proxy

        total_cap = 0.0
        covered_cap = 0.0
        hr_sum = co2_sum = nox_sum = so2_sum = 0.0

        for code in codes:
            prow = _plant_row(code, plnt)
            if prow is None:
                continue
            cap = prow[_PCOL["namecap"]]
            if pd.isna(cap) or cap <= 0:
                cap = 1.0  # unit weight if nameplate missing
            total_cap += cap
            hr = prow[_PCOL["heatrate"]]
            if pd.isna(hr) or not _passes_cutoff(prow[_PCOL["capfac"]], prow[_PCOL["netgen"]]):
                continue
            if not _passes_sanity(hr, tech):
                continue
            # For gas techs at coal-primary plants, the entire PLNT23 record is
            # coal-dominated — skip it so it doesn't contaminate the zone average.
            plant_fuel = str(prow[_PCOL["primfuel"]]).strip().upper()
            gas_tech   = tech in ("Gas:CT", "Gas:ST", "Gas:IC", "Gas:CC")
            if gas_tech and plant_fuel in _COAL_FUELS:
                continue
            covered_cap += cap
            hr_sum  += float(hr)  * cap
            co2_sum += float(prow[_PCOL["co2"]]) * cap
            nox_sum += float(prow[_PCOL["nox"]]) * cap
            so2_sum += float(prow[_PCOL["so2"]]) * cap

        if covered_cap == 0 or (total_cap > 0 and covered_cap / total_cap < 0.50):
            return proxy

        return {
            "AvgHtRate":         hr_sum  / covered_cap,
            "heat_rate_source":  "egrid_plant",
            "co2_RelRateMWh":    co2_sum / covered_cap,
            "nox_RelRateMWh":    nox_sum / covered_cap,
            "so2_RelRateMWh":    so2_sum / covered_cap,
            "emission_source":   "egrid_plant",
        }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _enrich_row(row: pd.Series, plnt: pd.DataFrame,
                unt_gen_lk: dict) -> dict:
    tech   = row["TechType"]
    status = row["status_category"]
    pm     = str(row["prime_mover"] if not pd.isna(row["prime_mover"]) else "").strip()
    is_grp = bool(row["is_grouped"])
    has_whr = not pd.isna(row["WasteHeat"])

    # 1. Zero-emission technologies (checked first — applies to proposed and operating alike)
    if tech in ZERO_EMISSION_TECHS:
        return _zero_emission()

    # 2. Proposed thermal: no operating history, use proxy
    if status == "proposed":
        return _apply_proxy(tech if tech in PROXY_DEFAULTS else "Other")

    # 3. Large CC CA (steam turbine half): no fuel consumption, not applicable
    if pm == "CA" and not is_grp:
        return {
            "AvgHtRate":         float("nan"),
            "heat_rate_source":  "not_applicable",
            "co2_RelRateMWh":    0.0,
            "nox_RelRateMWh":    0.0,
            "so2_RelRateMWh":    0.0,
            "emission_source":   "zero_direct_emission",
        }

    # 4. Large CC CT (linked to a CA): unit-level lookup first, proxy fallback
    #    Cannot use PLNT23 here — plant-level rate reflects combined-cycle, not simple-cycle.
    if has_whr and not is_grp:
        codes = parse_codes(row["plant_codes"])
        if len(codes) == 1:
            gen_id = str(row["generator_ids"]).strip()
            ug = unt_gen_lk.get((codes[0], gen_id))
            if ug is not None and _passes_sanity(ug["heat_rate"], tech):
                return {
                    "AvgHtRate":        ug["heat_rate"],
                    "heat_rate_source": "egrid_unit",
                    "co2_RelRateMWh":   ug["co2"],
                    "nox_RelRateMWh":   ug["nox"],
                    "so2_RelRateMWh":   ug["so2"],
                    "emission_source":  "egrid_unit",
                }
        return _apply_proxy("Gas:CT_cc")

    # 5. All remaining thermal: eGRID unit-level -> PLNT23 -> proxy fallback
    if tech in THERMAL_TECHS:
        return _enrich_egrid(row, plnt, unt_gen_lk)

    # Fallback for unrecognized tech types
    return _zero_emission()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(df: pd.DataFrame) -> None:
    print(f"\nHeat rate and emission enrichment summary ({len(df)} resources total):")

    src_counts = df["heat_rate_source"].value_counts()
    labels = {
        "egrid_unit":        "egrid_unit (unit-level UNT23/GEN23)",
        "egrid_plant":       "egrid_plant (plant-level PLNT23)",
        "proxy_tech_class":  "proxy_tech_class (proposed/fallback)",
        "proxy_cc_component":"proxy_cc_component (large CC CTs, unit-lk miss)",
        "not_applicable":    "not_applicable (zero-emission + CA)",
    }
    print("\n  By heat_rate_source:")
    for src, label in labels.items():
        n = src_counts.get(src, 0)
        print(f"    {label:<46} {n:3d} resources")

    print("\n  Thermal resources detail:")
    thermal = df[df["heat_rate_source"].isin(["egrid_unit", "egrid_plant", "proxy_tech_class", "proxy_cc_component"])].copy()

    def _avg(mask):
        vals = thermal.loc[mask, "AvgHtRate"].dropna()
        return f"{vals.mean():,.0f}" if len(vals) else "—"

    coal_mask    = thermal["TechType"] == "Coal"
    cc_small     = (thermal["TechType"] == "Gas:CC") & thermal["is_grouped"]
    cc_ca        = (thermal["prime_mover"] == "CA") & ~thermal["is_grouped"]
    cc_ct        = thermal["WasteHeat"].notna() & ~thermal["is_grouped"]
    ct_stand     = (thermal["TechType"] == "Gas:CT") & ~thermal["WasteHeat"].notna() & ~thermal["is_grouped"]
    ct_grp       = (thermal["TechType"] == "Gas:CT") & thermal["is_grouped"]
    gas_st       = thermal["TechType"] == "Gas:ST"
    gas_ic       = thermal["TechType"] == "Gas:IC"
    nuclear_mask = thermal["TechType"] == "Nuclear"

    print(f"    {'Coal':<30} avg HR: {_avg(coal_mask)} BTU/kWh  ({coal_mask.sum()} resources)")
    print(f"    {'Gas:CC small combined':<30} avg HR: {_avg(cc_small)} BTU/kWh  ({cc_small.sum()} resources)")
    print(f"    {'Gas:CC CA large':<30} avg HR: {_avg(cc_ca)} BTU/kWh  ({cc_ca.sum()} resources, proxy)")
    print(f"    {'Gas:CT CC-coupled':<30} avg HR: {_avg(cc_ct)} BTU/kWh  ({cc_ct.sum()} resources, proxy)")
    print(f"    {'Gas:CT standalone indiv':<30} avg HR: {_avg(ct_stand)} BTU/kWh  ({ct_stand.sum()} resources)")
    print(f"    {'Gas:CT grouped':<30} avg HR: {_avg(ct_grp)} BTU/kWh  ({ct_grp.sum()} resources)")
    print(f"    {'Gas:ST':<30} avg HR: {_avg(gas_st)} BTU/kWh  ({gas_st.sum()} resources)")
    print(f"    {'Gas:IC':<30} avg HR: {_avg(gas_ic)} BTU/kWh  ({gas_ic.sum()} resources)")
    print(f"    {'Nuclear':<30} avg HR: {_avg(nuclear_mask)} BTU/kWh  ({nuclear_mask.sum()} resources)")

    n_proxy_proposed = ((df["status_category"] == "proposed") & (df["heat_rate_source"] == "proxy_tech_class")).sum()
    n_proxy_fallback = ((df["status_category"] != "proposed") & (df["heat_rate_source"] == "proxy_tech_class")).sum()
    n_proposed_zero  = ((df["status_category"] == "proposed") & (df["heat_rate_source"] == "not_applicable")).sum()
    print(f"\n  Proposed thermal (proxy):  {n_proxy_proposed}")
    print(f"  Proposed zero-emission:    {n_proposed_zero}")
    print(f"  eGRID fallbacks (operating, low CF or sanity fail): {n_proxy_fallback}")


# ---------------------------------------------------------------------------
# Manuscript tables
# ---------------------------------------------------------------------------

def _manuscript_tables(df: pd.DataFrame) -> None:
    """Print Tables 1 and 2 for manuscript: individual large plants and aggregates."""

    TECH_LABELS = {
        "Coal": "Coal", "Gas:CC": "Gas CC", "Gas:CT": "Gas CT",
        "Gas:ST": "Gas ST", "Gas:IC": "Gas IC", "Nuclear": "Nuclear", "Other": "Other",
    }

    PLANT_DISPLAY = {
        "Comanche (CO)":             "Comanche",
        "Craig (CO)":                "Craig",
        "Front Range Power Plant":   "Front Range",
        "Rocky Mountain Energy Center": "RMEC",
    }

    def _pname(raw: str) -> str:
        return PLANT_DISPLAY.get(raw, raw)

    def _wavg(grp, col):
        return (grp[col] * grp["MaxCap"]).sum() / grp["MaxCap"].sum()

    indiv     = df[~df["is_grouped"] & (df["prime_mover"] != "CA")].copy()
    indiv_all = df[~df["is_grouped"]].copy()  # includes CA rows for CC blending

    # ── TABLE 1 ──────────────────────────────────────────────────────────────
    t1_rows = []

    # Coal egrid_unit: show unit number only when plant has multiple units
    coal_unit_df = indiv[(indiv["TechType"] == "Coal") & (indiv["heat_rate_source"] == "egrid_unit")]
    multi_unit_plants = set(coal_unit_df["plant_name"].str.strip().value_counts()[lambda x: x > 1].index)

    for _, r in coal_unit_df.iterrows():
        unit_num = str(r["Name"]).split("__")[-1] if "__" in str(r["Name"]) else ""
        plant    = str(r["plant_name"]).strip()
        base     = _pname(plant)
        display  = f"{base} {unit_num}" if (unit_num.isdigit() and plant in multi_unit_plants) else base
        t1_rows.append({"display": display, "tech": "Coal", "mw": r["MaxCap"],
                        "hr": r["AvgHtRate"], "co2": r["co2_RelRateMWh"],
                        "nox": r["nox_RelRateMWh"], "so2": r["so2_RelRateMWh"],
                        "source": "CEMS / unit-level", "_ord": 0})

    # Coal egrid_plant: aggregate by plant name
    for plant, grp in indiv[(indiv["TechType"] == "Coal") & (indiv["heat_rate_source"] == "egrid_plant")].groupby(indiv["plant_name"].str.strip()):
        mw = grp["MaxCap"].sum()
        t1_rows.append({"display": _pname(plant), "tech": "Coal", "mw": mw,
                        "hr": _wavg(grp, "AvgHtRate"), "co2": _wavg(grp, "co2_RelRateMWh"),
                        "nox": _wavg(grp, "nox_RelRateMWh"), "so2": _wavg(grp, "so2_RelRateMWh"),
                        "source": "CEMS / plant-level", "_ord": 0})

    # CC plants: blend CT fuel + CA output to get true combined-cycle rate
    # Heat rate = CT fuel input / (CT + CA output); emissions same denominator
    cc_ct_plant_names = set(
        indiv[indiv["WasteHeat"].notna() & (indiv["heat_rate_source"] == "egrid_unit")]
        ["plant_name"].str.strip()
    )
    for plant in sorted(cc_ct_plant_names):
        grp    = indiv_all[indiv_all["plant_name"].str.strip() == plant]
        ct_grp = grp[grp["WasteHeat"].notna()]          # CC-linked CTs only (excludes standalone ST)
        ca_grp = grp[grp["prime_mover"] == "CA"]
        total_mw = ct_grp["MaxCap"].sum() + ca_grp["MaxCap"].sum()
        if total_mw == 0:
            continue
        blended_hr  = (ct_grp["AvgHtRate"]      * ct_grp["MaxCap"]).sum() / total_mw
        blended_co2 = (ct_grp["co2_RelRateMWh"] * ct_grp["MaxCap"]).sum() / total_mw
        blended_nox = (ct_grp["nox_RelRateMWh"] * ct_grp["MaxCap"]).sum() / total_mw
        blended_so2 = (ct_grp["so2_RelRateMWh"] * ct_grp["MaxCap"]).sum() / total_mw
        t1_rows.append({"display": _pname(plant), "tech": "Gas CC", "mw": total_mw,
                        "hr": blended_hr, "co2": blended_co2,
                        "nox": blended_nox, "so2": blended_so2,
                        "source": "CEMS / unit-level", "_ord": 1})

    # Gas:CT standalone (no CC linkage): capacity-weighted fleet aggregate
    # Use full df (not indiv) so grouped zone resources are included alongside individual plants
    standalone_ct = df[
        (df["TechType"] == "Gas:CT") &
        df["WasteHeat"].isna() &
        (df["prime_mover"] != "CA") &
        (df["status_category"] != "proposed") &
        df["heat_rate_source"].isin(["egrid_unit", "egrid_plant", "proxy_tech_class"])
    ]
    if len(standalone_ct) > 0:
        mw = standalone_ct["MaxCap"].sum()
        t1_rows.append({"display": f"Gas CT fleet avg. ({len(standalone_ct)} plants)", "tech": "Gas CT",
                        "mw": mw,
                        "hr": _wavg(standalone_ct, "AvgHtRate"),
                        "co2": _wavg(standalone_ct, "co2_RelRateMWh"),
                        "nox": _wavg(standalone_ct, "nox_RelRateMWh"),
                        "so2": _wavg(standalone_ct, "so2_RelRateMWh"),
                        "source": "CEMS / eGRID / proxy", "_ord": 3})

    # Gas:ST egrid_unit: aggregate by plant name
    for plant, grp in indiv[(indiv["TechType"] == "Gas:ST") & (indiv["heat_rate_source"] == "egrid_unit")].groupby(indiv["plant_name"].str.strip()):
        mw = grp["MaxCap"].sum()
        t1_rows.append({"display": _pname(plant), "tech": "Gas ST", "mw": mw,
                        "hr": _wavg(grp, "AvgHtRate"), "co2": _wavg(grp, "co2_RelRateMWh"),
                        "nox": _wavg(grp, "nox_RelRateMWh"), "so2": _wavg(grp, "so2_RelRateMWh"),
                        "source": "CEMS / unit-level", "_ord": 2})

    t1_rows.sort(key=lambda x: (x["_ord"], x["display"]))

    print("\n" + "=" * 60)
    print("Manuscript Table — Heat and Emission Rates, Large Colorado Thermal Plants")
    print("  HR = BTU/kWh  |  CO2/NOx/SO2 = lb/MWh")
    print("=" * 60)
    print(f"  {'Plant':<37} {'Technology':<13} {'MW':>5}  {'HR':>7}  {'CO2':>6}  {'NOx':>5}  {'SO2':>5}  Source")
    print("  " + "-" * 100)
    prev_tech = None
    for r in t1_rows:
        if r["tech"] != prev_tech:
            print()
            prev_tech = r["tech"]
        print(f"  {r['display']:<37} {r['tech']:<13} {r['mw']:>5.0f}  {r['hr']:>7,.0f}  {r['co2']:>6,.0f}  {r['nox']:>5.3f}  {r['so2']:>5.3f}  {r['source']}")

    # ── TABLE — TECHNOLOGY CLASS PROXIES ────────────────────────────────────
    # Drawn directly from PROXY_DEFAULTS; internal-only keys excluded
    _PROXY_SKIP = {"Gas:CC_ca", "Gas:CT_cc", "Other"}
    proxy_rows = [
        {"tech": k, "hr": v["heat_rate"], "co2": v["co2"], "nox": v["nox"], "so2": v["so2"]}
        for k, v in PROXY_DEFAULTS.items()
        if k not in _PROXY_SKIP
    ]

    print("\n" + "=" * 60)
    print("Manuscript Table — Heat and Emission Rate Assumptions by Technology Class")
    print("  HR = BTU/kWh  |  CO2/NOx/SO2 = lb/MWh  |  Sources: EIA / EPA / AP-42")
    print("=" * 60)
    print(f"  {'Technology':<10} {'HR':>7}  {'CO2':>6}  {'NOx':>5}  {'SO2':>5}")
    print("  " + "-" * 45)
    for r in proxy_rows:
        label = TECH_LABELS.get(r["tech"], r["tech"])
        print(f"  {label:<10} {r['hr']:>7,.0f}  {r['co2']:>6,.0f}  {r['nox']:>5.2f}  {r['so2']:>5.2f}")

    # ── SAVE TSV FILES ───────────────────────────────────────────────────────
    out_dir = RESOURCES_CSV.parent

    # Large thermal plants table
    t1_path = out_dir / "manuscript_heat_emissions_large_plants.tsv"
    with open(t1_path, "w", encoding="utf-8") as f:
        f.write("Plant\tTechnology\tCapacity (MW)\tHeat Rate (BTU/kWh)\tCO2 (lb/MWh)\tNOx (lb/MWh)\tSO2 (lb/MWh)\n")
        for r in t1_rows:
            f.write(f"{r['display']}\t{r['tech']}\t{r['mw']:,.0f}\t{r['hr']:,.0f}\t{r['co2']:,.0f}\t{r['nox']:.2f}\t{r['so2']:.2f}\n")

    # Technology class proxy assumptions table
    t2_path = out_dir / "manuscript_heat_emissions_tech_proxies.tsv"
    with open(t2_path, "w", encoding="utf-8") as f:
        f.write("Technology\tHeat Rate (BTU/kWh)\tCO2 (lb/MWh)\tNOx (lb/MWh)\tSO2 (lb/MWh)\n")
        for r in proxy_rows:
            label = TECH_LABELS.get(r["tech"], r["tech"])
            f.write(f"{label}\t{r['hr']:,.0f}\t{r['co2']:,.0f}\t{r['nox']:.2f}\t{r['so2']:.2f}\n")

    print(f"\n  Saved: {t1_path.name}")
    print(f"  Saved: {t2_path.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Enrich resources with heat rates and emission rates.")
    parser.add_argument(
        "--redownload", action="store_true",
        help="Force a fresh eGRID download even if a cached copy already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print("=" * 60)
    print("Script 15: Heat Rates and Emission Rates")
    print("=" * 60)

    print("\n[1] eGRID")
    xlsx_path = download_egrid(force=args.redownload)
    plnt = load_egrid_plnt(xlsx_path)
    unt_gen_lk = build_unit_gen_lookup(xlsx_path)

    print("\n[2] Load resources")
    df = pd.read_csv(RESOURCES_CSV)
    print(f"  {len(df)} resources, {len(df.columns)} columns")

    print("\n[3] Enrich heat rates and emissions")
    results = [_enrich_row(row, plnt, unt_gen_lk) for _, row in df.iterrows()]
    enriched = pd.DataFrame(results, index=df.index)
    for col in NEW_COLS:
        df[col] = enriched[col]

    print("\n[4] Save")
    df.to_csv(RESOURCES_CSV, index=False)
    print(f"  Saved: {RESOURCES_CSV.name} ({len(df)} resources, {len(df.columns)} columns)")

    _print_summary(df)
    _manuscript_tables(df)


if __name__ == "__main__":
    main()
