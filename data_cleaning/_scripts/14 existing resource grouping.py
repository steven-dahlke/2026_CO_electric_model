"""
Script 14: Existing Resource Grouping

Reads colorado_generators.csv (Script 13 output, unchanged) and produces
colorado_resources.csv with one row per EnCompass model resource.

Grouping rules (priority order):
  1. Coal / Hydro:Pumped / Nuclear               -> always individual
  2. Proposed status (P/L/T/TS)                  -> project-level group (plant_name + tech_type)
  3. Storage:Battery, operating
       large (nameplate >= 100 MW) or no valid duration -> individual
       small with valid duration                  -> group by (zone, BA, rounded_duration_hours)
  4. Wind / Solar (operating)                    -> zone+BA group; East wind splits by nearest CF point
  5. Summer MW >= 100 MW (operating thermal)     -> individual
  6. Everything else (small operating)           -> group by (zone, BA, tech_type)

BA is included in all grouped resource keys so that generators in the same zone
but different balancing authorities are never conflated.

Prior-enrichment merge (added 2026-07-16): this script used to overwrite
colorado_resources.csv from scratch every run, silently discarding every
column added by Scripts 15-19 (O&M, heat rates, mincap/outages, storage,
retirement dates) and forcing a full 14->19 re-run for any change, even one
with nothing to do with grouping. merge_prior_enrichment() now carries those
columns forward for any resource whose Name and plant_codes/generator_ids
composition are unchanged from the prior file. A resource only loses its
enrichment (and needs 19-23 re-run) if its underlying generator composition
actually changed. See merge_prior_enrichment() docstring for the
RetirementDate-specific precedence rule.

CommissionDate / RetirementDate for grouped (operating) resources:
  CommissionDate is a capacity-weighted average across the group's generators
  (see _weighted_avg_date), rather than left blank.
  RetirementDate is propagated only when every generator in the group shares
  the same known/unknown retirement status. If a group mixes generators with
  an announced EIA-860 retirement_date and generators without one, the group
  is split into two resources (a "..._retiring" resource carrying the
  retiring generators' date, and the original name carrying the rest) so a
  single RetirementDate always applies to the whole resource it's set on.
"""

import os
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT  = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"
IN_CSV        = DATA_CLEANING / "resources" / "eia860" / "colorado_generators.csv"
OUT_CSV       = DATA_CLEANING / "resources" / "colorado_resources.csv"

SIZE_THRESHOLD_MW      = 100.0
SMALL_SOLAR_MW         =  20.0   # proposed solar below this threshold groups by zone (e.g. CSGs)
ALWAYS_INDIVIDUAL_TECH = {"Coal", "Hydro:Pumped", "Nuclear"}

ZONE_ORDER = ["North", "Denver", "East", "Mountain", "South", "West"]

TECH_COLORS = {
    "Coal":             "#5C4033",
    "Gas:CC":           "#455A64",
    "Gas:CT":           "#607D8B",
    "Gas:ST":           "#90A4AE",
    "Gas:IC":           "#CFD8DC",
    "Nuclear":          "#762A83",
    "Hydro":            "#35978F",
    "Hydro:Pumped":     "#01665E",
    "Solar:PV":         "#FDB863",
    "Solar:CSP":        "#F46D43",
    "Wind":             "#74C476",
    "Storage:Battery":  "#9970AB",
    "Other":            "#BDBDBD",
}
ALWAYS_GROUP_TECH      = {"Wind", "Solar:PV", "Solar:CSP"}
PROPOSED_STATUSES      = {"P", "L", "T", "TS"}

# East zone: three wind CF shapes at distinct geographic points (from encompass script 3)
EAST_WIND_POINTS = {
    "East_Wind_pt1_CF": (37.57, -102.47),   # southeastern East zone
    "East_Wind_pt2_CF": (38.94, -103.59),   # central East zone
    "East_Wind_pt3_CF": (40.14, -102.30),   # northeastern East zone
}

WIND_CF_SHAPE = {
    "North": "North_Wind_CF",
    "South": "South_Wind_CF",
    # East handled separately via nearest-point assignment
}
SOLAR_CF_SHAPE = {
    "Denver":   "Denver_Solar_CF",
    "East":     "East_Solar_CF",
    "Mountain": "Mountain_Solar_CF",
    "North":    "North_Solar_CF",
    "South":    "South_Solar_CF",
    "West":     "West_Solar_CF",
}

OUTPUT_COLS = [
    "resource_name", "zone", "tech_type", "status_category", "group_type",
    "is_grouped", "unit_count", "nameplate_mw", "summer_mw",
    "storage_mwh", "max_charge_mw", "max_discharge_mw",
    "commission_date", "retirement_date", "encompass_cf_shape",
    "plant_codes", "generator_ids", "plant_name",
    "energy_source", "prime_mover", "ba_code", "filter_source",
    "waste_heat_resource", "waste_heat_bypass",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(name: str) -> str:
    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _safe_tech(tech: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", tech)


def _most_common(series: pd.Series):
    vc = series.dropna().value_counts()
    return vc.index[0] if len(vc) else None


def _agg_list(series: pd.Series) -> str:
    return "; ".join(sorted(str(int(v)) if isinstance(v, float) else str(v)
                            for v in series.dropna().unique()))


def _weighted_avg_date(dates: pd.Series, weights: pd.Series):
    """Capacity-weighted average of a set of dates, returned as a 'YYYY-MM-DD' string.

    Used to give grouped resources (multiple generators of different vintages
    merged into one EnCompass resource) a representative CommissionDate instead
    of leaving it blank. Returns None if no date/weight pairs are usable.
    """
    dt = pd.to_datetime(dates, errors="coerce")
    w  = pd.to_numeric(weights, errors="coerce")
    mask = dt.notna() & w.notna() & (w > 0)
    if not mask.any():
        return None
    ordinals = dt[mask].map(lambda d: d.toordinal())
    avg_ordinal = round((ordinals * w[mask]).sum() / w[mask].sum())
    return pd.Timestamp.fromordinal(int(avg_ordinal)).strftime("%Y-%m-%d")


def nearest_east_wind_point(lat: float, lon: float) -> str:
    """Return the CF shape name of the closest East zone wind point."""
    best, best_d = None, float("inf")
    for name, (pt_lat, pt_lon) in EAST_WIND_POINTS.items():
        d = (lat - pt_lat) ** 2 + (lon - pt_lon) ** 2
        if d < best_d:
            best_d, best = d, name
    return best


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_generators() -> pd.DataFrame:
    df = pd.read_csv(IN_CSV, dtype={"generator_id": str})
    df["plant_code"]   = pd.to_numeric(df["plant_code"],   errors="coerce")
    df["summer_mw"]    = pd.to_numeric(df["summer_mw"],    errors="coerce")
    df["nameplate_mw"] = pd.to_numeric(df["nameplate_mw"], errors="coerce")
    df["latitude"]     = pd.to_numeric(df["latitude"],     errors="coerce")
    df["longitude"]    = pd.to_numeric(df["longitude"],    errors="coerce")
    for col in ["storage_mwh", "max_charge_mw", "max_discharge_mw"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = float("nan")
    df = df.dropna(subset=["plant_code"])
    df["plant_code"] = df["plant_code"].astype(int)

    if "zone_assignment" in df.columns and "zone" not in df.columns:
        df = df.rename(columns={"zone_assignment": "zone"})

    required = ["plant_code", "generator_id", "tech_type", "status",
                "zone", "summer_mw", "latitude", "longitude"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in input CSV: {missing}")

    # Drop generators with no recognized technology type.
    # These are non-dispatchable niche resources (landfill/digester gas IC engines,
    # waste-heat steam turbines, mothballed fuel oil GTs) with negligible aggregate MW
    # that add no meaningful dispatch signal to the model.
    n_other = (df["tech_type"] == "Other").sum()
    if n_other:
        dropped = df[df["tech_type"] == "Other"][["plant_code", "plant_name", "prime_mover", "energy_source"]].drop_duplicates()
        print(f"  Excluding {n_other} 'Other' TechType generators from model:")
        for _, r in dropped.iterrows():
            print(f"    plant {int(r['plant_code'])}  {str(r.get('plant_name','')):<36}  {r['prime_mover']}/{r['energy_source']}")
        df = df[df["tech_type"] != "Other"].copy()

    print(f"  {len(df)} generators from {IN_CSV.name}")
    return df


# ---------------------------------------------------------------------------
# Classify
# ---------------------------------------------------------------------------

def classify(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    keys, types, cf_shapes = [], [], []

    # Plants that have at least one CA generator are CC plants; units there get
    # merged into a single combined zone resource rather than split CA/CT.
    cc_plant_codes: set[int] = set(
        df.loc[df["prime_mover"] == "CA", "plant_code"].dropna().astype(int)
    )

    for _, r in df.iterrows():
        tech   = str(r.get("tech_type", "")).strip()
        status = str(r.get("status",    "")).strip()
        mw     = float(r["summer_mw"])    if pd.notna(r.get("summer_mw"))    else 0.0
        mw_np  = float(r["nameplate_mw"]) if pd.notna(r.get("nameplate_mw")) else 0.0
        zone   = str(r.get("zone",     "")).strip()
        ba     = str(r.get("ba_code",  "")).strip().upper()
        pc     = int(r["plant_code"])
        gid    = str(r["generator_id"]).strip()

        # Rule 1: always-individual tech types
        if tech in ALWAYS_INDIVIDUAL_TECH:
            keys.append(f"ind_{pc}_{gid}")
            types.append("individual_tech")
            cf_shapes.append(None)

        # Rule 2: proposed / under construction
        # Small proposed solar (< SIZE_THRESHOLD_MW nameplate) groups by zone+BA so
        # tiny projects like community solar gardens don't get individual entries.
        elif status in PROPOSED_STATUSES:
            if tech in {"Solar:PV", "Solar:CSP"} and 0 < mw_np < SMALL_SOLAR_MW:
                keys.append(f"prop_{zone}_{ba}_{_safe_tech(tech)}_small")
                types.append("proposed_small_solar")
            else:
                keys.append(f"prop_{_safe(r.get('plant_name', ''))}_{_safe_tech(tech)}")
                types.append("proposed")
            cf_shapes.append(
                SOLAR_CF_SHAPE.get(zone) if tech in {"Solar:PV", "Solar:CSP"} else None
            )

        # Rule 3: operating battery storage — size + duration check
        elif tech == "Storage:Battery":
            mwh      = r.get("storage_mwh")
            mwh      = float(mwh) if pd.notna(mwh) and float(mwh) > 0 else None
            size_ref = mw_np if mw_np > 0 else mw   # nameplate preferred; summer fallback
            dur      = round(mwh / size_ref) if (mwh and size_ref > 0) else None
            if size_ref >= SIZE_THRESHOLD_MW or dur is None:
                keys.append(f"ind_{pc}_{gid}")
                types.append("individual_tech")
            else:
                keys.append(f"grp_{zone}_{ba}_battery_{dur}hr")
                types.append("small_battery")
            cf_shapes.append(None)

        # Rule 4: operating wind / solar — group by zone + BA; East wind splits by CF point
        elif tech in ALWAYS_GROUP_TECH:
            if zone == "East" and tech == "Wind":
                lat    = float(r["latitude"])  if pd.notna(r.get("latitude"))  else 39.0
                lon    = float(r["longitude"]) if pd.notna(r.get("longitude")) else -103.0
                cf_key = nearest_east_wind_point(lat, lon)
                pt_num = cf_key.replace("East_Wind_", "").replace("_CF", "")   # "pt1"/"pt2"/"pt3"
                keys.append(f"grp_{zone}_{ba}_Wind_{pt_num}")
                cf_shapes.append(cf_key)
            else:
                cf_key = WIND_CF_SHAPE.get(zone) or SOLAR_CF_SHAPE.get(zone)
                keys.append(f"grp_{zone}_{ba}_{_safe_tech(tech)}")
                cf_shapes.append(cf_key)
            types.append("renewable_zone")

        # Rule 5: large operating thermal — individual
        # Use nameplate_mw as the size reference (preferred over summer_mw) because
        # EIA-860 can assign aggregate plant summer capacity to one unit (e.g. JM Shafer LMA).
        elif (mw_np if mw_np > 0 else mw) >= SIZE_THRESHOLD_MW:
            keys.append(f"ind_{pc}_{gid}")
            types.append("large_thermal")
            cf_shapes.append(None)

        # Rule 6: small operating — group by zone + BA + tech
        # CA and CT units at CC plants form one combined zone resource.
        # GT units are always simple-cycle even when co-located at a CC plant, so
        # they stay in the regular zone+BA+tech group alongside other standalone GTs.
        else:
            pm = str(r.get("prime_mover", "")).strip()
            if pc in cc_plant_codes and pm in {"CA", "CT"}:
                keys.append(f"grp_{zone}_{ba}_GasCC")
                types.append("small_cc")
            else:
                keys.append(f"grp_{zone}_{ba}_{_safe_tech(tech)}")
                types.append("small_group")
            cf_shapes.append(None)

    df["grouping_key"]      = keys
    df["group_type"]        = types
    df["grouping_cf_shape"] = cf_shapes
    df["status_category"]   = df["status"].apply(
        lambda s: "proposed" if s in PROPOSED_STATUSES else "operating"
    )

    print("\n  Grouping type breakdown:")
    for gt, cnt in df["group_type"].value_counts().items():
        print(f"    {gt:<20}: {cnt:4d} generators")
    return df


# ---------------------------------------------------------------------------
# Build individual resources
# ---------------------------------------------------------------------------

def build_individual(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["group_type"].isin({"individual_tech", "large_thermal"})].copy()
    sub["resource_name"]      = sub.apply(
        lambda r: f"{_safe(r.get('plant_name', str(r['plant_code'])))}__{r['generator_id']}",
        axis=1,
    )
    sub["is_grouped"]         = False
    sub["unit_count"]         = 1
    sub["plant_codes"]        = sub["plant_code"].astype(str)
    sub["generator_ids"]      = sub["generator_id"].astype(str)
    sub["encompass_cf_shape"] = None
    print(f"  Individual resources:  {len(sub)}")
    return sub


# ---------------------------------------------------------------------------
# Build proposed resources (project-level grouping)
# ---------------------------------------------------------------------------

def build_proposed(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["group_type"].isin({"proposed", "proposed_small_solar"})].copy()
    records = []

    for key, grp in sub.groupby("grouping_key", sort=True):
        tech       = _most_common(grp["tech_type"])
        zone       = _most_common(grp["zone"])
        ba         = _most_common(grp.get("ba_code", pd.Series(dtype=str)))
        plant_name = _most_common(grp.get("plant_name", pd.Series(dtype=str)))
        n          = len(grp)
        gt         = _most_common(grp["group_type"])

        if gt == "proposed_small_solar":
            rname = f"{zone}_{ba}_{_safe_tech(tech or '')}_proposed_small"
        else:
            rname = f"{_safe(plant_name or key)}_{_safe_tech(tech or '')}_proposed"

        dates = grp["commission_date"].dropna()
        comm  = dates.min() if len(dates) else None

        cf_shape = _most_common(grp["grouping_cf_shape"])

        records.append({
            "resource_name":      rname,
            "zone":               zone,
            "tech_type":          tech,
            "status_category":    "proposed",
            "group_type":         gt,
            "is_grouped":         n > 1,
            "unit_count":         n,
            "nameplate_mw":       grp["nameplate_mw"].sum(min_count=1),
            "summer_mw":          grp["summer_mw"].sum(min_count=1),
            "storage_mwh":        grp["storage_mwh"].sum(min_count=1),
            "max_charge_mw":      grp["max_charge_mw"].sum(min_count=1),
            "max_discharge_mw":   grp["max_discharge_mw"].sum(min_count=1),
            "commission_date":    comm,
            "retirement_date":    None,
            "encompass_cf_shape": cf_shape,
            "plant_codes":        _agg_list(grp["plant_code"]),
            "generator_ids":      _agg_list(grp["generator_id"]),
            "plant_name":         plant_name if n == 1 else _agg_list(grp.get("plant_name", pd.Series(dtype=str))),
            "energy_source":      _most_common(grp.get("energy_source", pd.Series(dtype=str))),
            "prime_mover":        _most_common(grp.get("prime_mover",   pd.Series(dtype=str))),
            "ba_code":            _most_common(grp.get("ba_code",       pd.Series(dtype=str))),
            "filter_source":      _most_common(grp.get("filter_source", pd.Series(dtype=str))),
        })

    result = pd.DataFrame(records)
    print(f"  Proposed resources:    {len(result)}")
    return result


# ---------------------------------------------------------------------------
# Build grouped operating resources (renewables, small thermal, small batteries)
# ---------------------------------------------------------------------------

def _build_group_record(grp: pd.DataFrame, name_suffix: str = "") -> dict:
    """Build one resource record from a (sub-)group of generators.

    CommissionDate is a capacity-weighted average across the group's generators
    (see _weighted_avg_date). RetirementDate is only set when every generator in
    `grp` shares a known retirement_date (i.e. this sub-group is 100% retiring or
    0% retiring) — callers with a mixed group must split it before calling this.
    """
    tech     = _most_common(grp["tech_type"])
    zone     = _most_common(grp["zone"])
    ba       = _most_common(grp.get("ba_code", pd.Series(dtype=str)))
    gt       = _most_common(grp["group_type"])
    n        = len(grp)
    cf_shape = _most_common(grp["grouping_cf_shape"])

    if gt == "small_battery":
        stor_mwh  = grp["storage_mwh"].sum(min_count=1)
        chg_mw    = grp["max_charge_mw"].sum(min_count=1)
        dchg_mw   = grp["max_discharge_mw"].sum(min_count=1)
        np_sum    = grp["nameplate_mw"].sum()
        dur       = round(float(stor_mwh) / np_sum) if (pd.notna(stor_mwh) and np_sum > 0) else "?"
        rname     = f"{zone}_{ba}_battery_{dur}hr_small"
    else:
        stor_mwh = chg_mw = dchg_mw = None
        if tech in {"Wind", "Solar:PV", "Solar:CSP"}:
            if cf_shape and "pt" in cf_shape:
                # East wind: cf_shape = "East_Wind_pt1_CF" -> "East_Wind_pt1_WACM_existing"
                rname = f"{cf_shape.replace('_CF', '')}_{ba}_existing"
            else:
                rname = f"{zone}_{ba}_{_safe_tech(tech or '')}_existing"
        elif gt == "small_cc":
            tech = "Gas:CC"
            rname = f"{zone}_{ba}_GasCC_small"
        else:
            rname = f"{zone}_{ba}_{_safe_tech(tech or '')}_small"

    rname += name_suffix

    comm = _weighted_avg_date(grp["commission_date"], grp["nameplate_mw"])

    ret_dates = grp["retirement_date"].dropna()
    retirement = ret_dates.min() if len(ret_dates) == n and n > 0 else None

    return {
        "resource_name":      rname,
        "zone":               zone,
        "tech_type":          tech,
        "status_category":    "operating",
        "group_type":         gt,
        "is_grouped":         True,
        "unit_count":         n,
        "nameplate_mw":       grp["nameplate_mw"].sum(min_count=1),
        "summer_mw":          grp["summer_mw"].sum(min_count=1),
        "storage_mwh":        stor_mwh,
        "max_charge_mw":      chg_mw,
        "max_discharge_mw":   dchg_mw,
        "commission_date":    comm,
        "retirement_date":    retirement,
        "encompass_cf_shape": cf_shape,
        "plant_codes":        _agg_list(grp["plant_code"]),
        "generator_ids":      _agg_list(grp["generator_id"]),
        "plant_name":         _agg_list(grp.get("plant_name", pd.Series(dtype=str))),
        "energy_source":      _most_common(grp.get("energy_source", pd.Series(dtype=str))),
        "prime_mover":        _most_common(grp.get("prime_mover",   pd.Series(dtype=str))),
        "ba_code":            ba,
        "filter_source":      _most_common(grp.get("filter_source", pd.Series(dtype=str))),
    }


def build_grouped(df: pd.DataFrame) -> pd.DataFrame:
    sub = df[df["group_type"].isin({"renewable_zone", "small_group", "small_battery", "small_cc"})].copy()
    records = []
    n_split = 0

    for key, grp in sub.groupby("grouping_key", sort=True):
        n_retiring = grp["retirement_date"].notna().sum()

        if 0 < n_retiring < len(grp):
            # Mixed group: some generators have an announced EIA-860 retirement,
            # others don't. A single RetirementDate can't represent both, so split
            # into a retiring sub-resource and a continuing sub-resource.
            retiring_mask = grp["retirement_date"].notna()
            records.append(_build_group_record(grp[retiring_mask],  name_suffix="_retiring"))
            records.append(_build_group_record(grp[~retiring_mask], name_suffix=""))
            n_split += 1
        else:
            records.append(_build_group_record(grp))

    result = pd.DataFrame(records)
    print(f"  Grouped resources:     {len(result)}"
          f"  ({n_split} group(s) split on mixed retirement status)")
    return result


# ---------------------------------------------------------------------------
# CC waste heat linkage
# ---------------------------------------------------------------------------

def _parse_codes(s) -> list:
    """Parse semicolon-separated plant codes string (e.g. '469; 6112') to list of ints."""
    if pd.isna(s) or str(s).strip() == "":
        return []
    return [int(x.strip()) for x in str(s).split(";") if x.strip().lstrip("-").isdigit()]


def _assign_cc_linkage(df: pd.DataFrame) -> pd.DataFrame:
    """Add waste_heat_resource and waste_heat_bypass columns for large CC plant CTs.

    Only applies to individual (non-grouped) resources: large CC plants where each
    CA and CT unit is its own resource. Small CC plants are combined into one zone
    resource and need no linkage.
    """
    df = df.copy()
    df["WasteHeat"] = None
    df["WHBypass"] = None

    indiv = df[~df["is_grouped"]]
    ca_rows = indiv[indiv["prime_mover"] == "CA"][["plant_codes", "Name"]]
    ca_map: dict[int, str] = {}
    for _, r in ca_rows.iterrows():
        for code in _parse_codes(r["plant_codes"]):
            ca_map[code] = r["Name"]

    def _link(row):
        if row["is_grouped"] or row["prime_mover"] != "CT":
            return row
        for code in _parse_codes(row["plant_codes"]):
            if code in ca_map:
                row["WasteHeat"] = ca_map[code]
                row["WHBypass"] = "Yes"
                return row
        return row

    df = df.apply(_link, axis=1)

    linked_ct = df["WasteHeat"].notna().sum()
    n_ca = (df["prime_mover"] == "CA").sum()
    n_plants = len(ca_map)
    print(f"  CC linkage assigned: {linked_ct} CT resources linked to "
          f"{n_ca} CA resources at {n_plants} plants")

    return df


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

def assemble(individual: pd.DataFrame, proposed: pd.DataFrame,
             grouped: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for part in [individual, proposed, grouped]:
        part = part.copy()
        for col in OUTPUT_COLS:
            if col not in part.columns:
                part[col] = None
        parts.append(part[OUTPUT_COLS])

    result = pd.concat(parts, ignore_index=True)

    # Rename internal column names to EnCompass parameter names
    result = result.rename(columns={
        "resource_name":      "Name",
        "zone":               "Area",
        "tech_type":          "TechType",
        "unit_count":         "Units",
        "summer_mw":          "MaxCap",
        "storage_mwh":        "MaxStorage",
        "max_charge_mw":      "PaybckCap",
        "commission_date":    "CommissionDate",
        "retirement_date":    "RetirementDate",
        "encompass_cf_shape": "NetGenLim",
        "waste_heat_resource":"WasteHeat",
        "waste_heat_bypass":  "WHBypass",
    })

    result = result.sort_values(["Area", "TechType", "Name"]).reset_index(drop=True)

    dupes = result.loc[result["Name"].duplicated(), "Name"].tolist()
    if dupes:
        raise ValueError(f"Duplicate Name values — fix naming logic: {dupes}")

    return result


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_summary(df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("RESOURCE GROUPING SUMMARY")
    print("=" * 72)
    print(f"\nTotal resources: {len(df)}")
    print(f"  Individual: {(~df['is_grouped']).sum()}"
          f"  |  Grouped/project-level: {df['is_grouped'].sum()}")

    print("\nArea x TechType (n resources | MaxCap MW):")
    pivot = df.groupby(["Area", "TechType"]).agg(
        n=("Name", "count"),
        mw=("MaxCap", "sum"),
    )
    print(pivot.to_string())

    print("\nEast wind CF shape assignment:")
    ew = df[df["Name"].str.contains("East_Wind_pt", na=False)]
    if len(ew):
        for _, r in ew.iterrows():
            print(f"  {r['Name']:<32} {int(r['Units']):3d} units"
                  f"  {r['MaxCap']:8.1f} MW  -> {r['NetGenLim']}")
    else:
        print("  (no East wind groups found)")

    bat = df[df["TechType"] == "Storage:Battery"]
    if len(bat):
        print(f"\nBattery resources ({len(bat)} total):")
        for _, r in bat.sort_values("Name").iterrows():
            label = f"{int(r['Units'])} units grouped" if r["is_grouped"] else "individual"
            mwh_str = f"  {r['MaxStorage']:.0f} MWh" if pd.notna(r.get("MaxStorage")) else ""
            print(f"  {r['Name']:<42} {r['nameplate_mw']:7.1f} MW{mwh_str}  [{label}]")

    missing_cf = df[
        df["TechType"].isin({"Wind", "Solar:PV", "Solar:CSP"})
        & df["NetGenLim"].isna()
    ]
    if len(missing_cf):
        print(f"\nWARNING: {len(missing_cf)} wind/solar resources missing CF shape:")
        print(missing_cf[["Name", "TechType", "Area"]].to_string())
    else:
        print("\nAll wind/solar resources have CF shapes assigned.")

    in_mw  = pd.read_csv(IN_CSV)["summer_mw"].sum(min_count=1)
    out_mw = df["MaxCap"].sum(min_count=1)
    print(f"\nMW balance: input={in_mw:.1f}  output={out_mw:.1f}"
          f"  diff={out_mw - in_mw:.1f} (NaN gap from proposed units with no summer_mw)")


# ---------------------------------------------------------------------------
# Chart and Excel outputs
# ---------------------------------------------------------------------------

def _chart_mw(df: pd.DataFrame) -> pd.DataFrame:
    """Return df with chart_mw: summer_mw for operating, nameplate_mw fallback for proposed."""
    df = df.copy()
    df["chart_mw"] = df["MaxCap"].fillna(df["nameplate_mw"])
    return df


def save_chart(df: pd.DataFrame, out_path: Path) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    df = _chart_mw(df)

    combined = (df.groupby(["Area", "TechType"])["chart_mw"]
                .sum().unstack(fill_value=0))

    zones = [z for z in ZONE_ORDER if z in combined.index]
    techs = [t for t in TECH_COLORS
             if t in combined.columns and combined[t].sum() > 0]
    combined = combined.reindex(index=zones, columns=techs, fill_value=0)

    with plt.rc_context({"font.family": "Times New Roman", "font.size": 19}):
        fig, ax = plt.subplots(figsize=(10, 6))

        x       = np.arange(len(zones))
        bar_w   = 0.55
        bottoms = np.zeros(len(zones))

        for tech in techs:
            vals = combined[tech].values / 1000
            ax.bar(x, vals, bottom=bottoms, width=bar_w,
                   color=TECH_COLORS[tech], label=tech, linewidth=0)
            bottoms += vals

        ax.set_xticks(x)
        ax.set_xticklabels(zones, fontsize=19)
        ax.set_ylabel("Capacity (GW)", fontsize=19)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
        ax.tick_params(axis="y", labelsize=17)
        ax.spines[["top", "right"]].set_visible(False)

        ax.legend(
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            fontsize=19,
            frameon=False,
            borderpad=0.8,
            labelspacing=0.5,
        )

        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    print(f"  Chart  -> {out_path.name}")


def save_excel_pivot(df: pd.DataFrame, out_path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    df   = _chart_mw(df)
    zones = [z for z in ZONE_ORDER if z in df["Area"].values]

    def _pivot(mask):
        return (df[mask]
                .groupby(["TechType", "Area"])["chart_mw"].sum()
                .unstack(fill_value=0)
                .reindex(columns=zones, fill_value=0))

    op   = _pivot(df["status_category"] == "operating")
    prop = _pivot(df["status_category"] == "proposed")
    tech_order = [t for t in TECH_COLORS if t in op.index or t in prop.index]
    op   = op.reindex(tech_order).dropna(how="all")
    prop = prop.reindex(tech_order).dropna(how="all")

    wb = Workbook()
    ws = wb.active
    ws.title = "Resources by Zone"

    bold   = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center")

    def fill(hex_str):
        return PatternFill("solid", fgColor=hex_str)

    def write_section(pivot, label, header_hex, row_start):
        ws.cell(row_start, 1, label).font = Font(bold=True, size=11)
        hr = row_start + 1
        ws.cell(hr, 1, "Technology").font = bold
        ws.cell(hr, 1).fill = fill(header_hex)
        for ci, z in enumerate(zones, 2):
            c = ws.cell(hr, ci, z)
            c.font = bold; c.alignment = center; c.fill = fill(header_hex)
        total_col = len(zones) + 2
        ws.cell(hr, total_col, "Total").font = bold
        ws.cell(hr, total_col).alignment = center
        ws.cell(hr, total_col).fill = fill(header_hex)

        for ri, tech in enumerate(pivot.index):
            r = hr + 1 + ri
            ws.cell(r, 1, tech)
            row_sum = 0
            for ci, z in enumerate(zones, 2):
                val = pivot.loc[tech, z] if z in pivot.columns else 0
                if val > 0:
                    c = ws.cell(r, ci, round(val, 0))
                    c.alignment = center
                    row_sum += val
                else:
                    ws.cell(r, ci, "—").alignment = center
            ws.cell(r, total_col, round(row_sum, 0)).alignment = center

        tr = hr + 1 + len(pivot)
        ws.cell(tr, 1, "Total").font = bold
        ws.cell(tr, 1).fill = fill(header_hex)
        grand = 0
        for ci, z in enumerate(zones, 2):
            v = round(pivot[z].sum(), 0) if z in pivot.columns else 0
            c = ws.cell(tr, ci, v)
            c.font = bold; c.alignment = center; c.fill = fill(header_hex)
            grand += v
        c = ws.cell(tr, total_col, round(grand, 0))
        c.font = bold; c.alignment = center; c.fill = fill(header_hex)

        return tr + 1  # next free row

    next_row = write_section(op,   "Operating (Summer MW)",   "DDEEFF", 1)
    write_section(prop, "Proposed (Nameplate MW)", "FFF3CD", next_row + 1)

    ws.column_dimensions["A"].width = 20
    for ci in range(2, len(zones) + 3):
        ws.column_dimensions[get_column_letter(ci)].width = 11

    wb.save(out_path)
    print(f"  Excel  -> {out_path.name}")


# ---------------------------------------------------------------------------
# Merge with prior enrichment (Scripts 15-19 output)
# ---------------------------------------------------------------------------

# Columns Script 14 itself computes fresh every run (post-rename names from
# assemble()). Everything else found in a prior colorado_resources.csv belongs
# to a downstream script (15-19) and should be preserved across a Script 14
# re-run, not silently wiped -- that was the whole reason full 14->19 re-runs
# were needed for every change, even ones with nothing to do with grouping.
STRUCTURAL_COLS = [
    "Name", "Area", "TechType", "status_category", "group_type", "is_grouped",
    "Units", "nameplate_mw", "MaxCap", "MaxStorage", "PaybckCap",
    "max_discharge_mw", "CommissionDate", "RetirementDate", "NetGenLim",
    "plant_codes", "generator_ids", "plant_name", "energy_source",
    "prime_mover", "ba_code", "filter_source", "WasteHeat", "WHBypass",
]


def merge_prior_enrichment(result: pd.DataFrame, prior_csv: Path) -> pd.DataFrame:
    """Carry forward Script 15-19 enrichment columns for unchanged resources.

    A resource is "unchanged" if its Name AND its underlying plant_codes/
    generator_ids composition both match the prior file exactly. Composition
    is checked deliberately (not just Name) -- if the same resource name ever
    ends up representing a different set of generators, silently preserving
    old enrichment values would be wrong, not just unnecessary.

    RetirementDate/retirement_life_source get special handling since Script 14
    also writes RetirementDate itself (for resources with a real EIA-860
    announced date): a freshly-computed non-blank RetirementDate always wins
    (an announced date takes precedence over anything Script 19 derived), and
    only a blank fresh value falls back to the prior file's value.
    """
    if not prior_csv.exists():
        print(f"  No prior {prior_csv.name} found -- nothing to merge, all "
              f"enrichment columns start blank (expected on a first run).")
        return result

    prior = pd.read_csv(prior_csv, dtype=str)
    enrichment_cols = [c for c in prior.columns
                        if c not in STRUCTURAL_COLS and c != "retirement_life_source"]

    result = result.copy()
    for col in enrichment_cols:
        if col not in result.columns:
            result[col] = pd.NA
    if "retirement_life_source" not in result.columns and "retirement_life_source" in prior.columns:
        result["retirement_life_source"] = pd.NA

    prior_idx = prior.set_index("Name")
    n_matched, n_new, n_changed = 0, 0, 0

    for i, row in result.iterrows():
        name = row["Name"]
        if name not in prior_idx.index:
            n_new += 1
            continue

        p = prior_idx.loc[name]
        if isinstance(p, pd.DataFrame):   # duplicate Name in prior file -- skip, treat as new
            continue

        same_composition = (str(row.get("plant_codes")) == str(p.get("plant_codes"))
                             and str(row.get("generator_ids")) == str(p.get("generator_ids")))
        if not same_composition:
            n_changed += 1
            continue

        n_matched += 1
        for col in enrichment_cols:
            if col in p.index:
                result.at[i, col] = p[col]

        fresh_retirement = row.get("RetirementDate")
        if (pd.isna(fresh_retirement) or not str(fresh_retirement).strip()) \
                and "RetirementDate" in p.index and pd.notna(p.get("RetirementDate")) \
                and str(p.get("RetirementDate")).strip():
            result.at[i, "RetirementDate"] = p["RetirementDate"]
            if "retirement_life_source" in p.index:
                result.at[i, "retirement_life_source"] = p["retirement_life_source"]

    print(f"  Merged prior enrichment: {n_matched} unchanged, {n_new} new/renamed, "
          f"{n_changed} composition changed (enrichment cleared, needs Scripts 15-19)")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("\n[1/6] Loading generator inventory...")
    df = load_generators()

    print("\n[2/6] Classifying generators...")
    df = classify(df)

    print("\n[3/6] Building resource groups...")
    individual = build_individual(df)
    proposed   = build_proposed(df)
    grouped    = build_grouped(df)

    print("\n[4/6] Assembling...")
    result = assemble(individual, proposed, grouped)
    result = _assign_cc_linkage(result)

    print("\n[5/6] Merging prior Script 15-19 enrichment...")
    result = merge_prior_enrichment(result, OUT_CSV)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_CSV, index=False)
    print(f"  Wrote {len(result)} resources x {len(result.columns)} columns -> {OUT_CSV.name}")

    print_summary(result)

    print("\n[6/6] Saving chart and Excel pivot...")
    out_dir = OUT_CSV.parent
    save_chart(result, out_dir / "existing_resources_by_zone.png")
    save_excel_pivot(result, out_dir / "existing_resources_pivot.xlsx")

    print("\nDone.")


if __name__ == "__main__":
    main()
