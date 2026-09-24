"""
PyPSA Milestone 4: existing fleet & candidate technology assembly.

Turns colorado_resources.csv (existing fleet) and candidate_technology_parameters.csv +
atb_candidate_lookup.csv (candidate new-build technologies) into PyPSA-ready
Generator/StorageUnit specifications -- not yet attached to a live Network (no buses exist yet;
that's Milestone 5). See pypsa/Documentation/build_plan.md, Milestone 4, for the full mapping
table and reasoning behind each field.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root
from model_helpers import (
    HYBRID_BATTERY_SUFFIX,
    HYBRID_CARRIER,
    WIND_ZONE_POINTS,
    parse_wind_point,
)

PROJECT_ROOT = find_project_root()
RESOURCES_DIR = PROJECT_ROOT / "data_cleaning" / "resources"
OUT_DIR = PROJECT_ROOT / "pypsa" / "diagnostics"

RESOURCES_PATH = RESOURCES_DIR / "colorado_resources.csv"
FUEL_PRICE_PATH = RESOURCES_DIR / "costs" / "fuel_price_lookup.csv"
CANDIDATE_PARAMS_PATH = RESOURCES_DIR / "candidate_technology_parameters.csv"
ATB_LOOKUP_PATH = RESOURCES_DIR / "costs" / "atb" / "atb_candidate_lookup.csv"

GENERATOR_COLS = ["bus", "carrier", "p_nom", "p_nom_extendable", "marginal_cost", "capital_cost", "p_min_pu"]
STORAGE_COLS = ["bus", "carrier", "p_nom", "p_nom_extendable", "marginal_cost", "capital_cost", "max_hours"]

ALL_ZONES = ["Denver", "East", "Mountain", "North", "South", "West"]
ATB_SCENARIO = "Moderate"
# Default-off until Milestone 8c: the naive mapping of this row (storage_duration_hours set,
# no solar generation side) would emit another battery, not a hybrid. hybrid_candidates=True
# drops the exclusion and splits the row into a paired Generator + StorageUnit.
# See pypsa/_plans/milestone_8c_hybrid_solar_storage.md.
EXCLUDED_CANDIDATE_TECHS = {HYBRID_CARRIER}

# Existing-fleet aggregation (2026-08-17, added after Milestone 5's first solve attempt showed the
# LP was too large/slow at full component granularity -- see build_plan.md's Milestone 4 section
# for the full reasoning). Safe to merge because all zero or near-zero marginal cost -- no real
# merit-order structure to distort (unlike Gas:CT/CC/IC/ST/Coal, deliberately left untouched: real
# cost dispersion checked directly, e.g. North's Gas:CT units span $63-69/MWh, and this
# cost-minimization LP's build decisions are driven by exactly that kind of price signal). Merges
# across BA as well as within -- checked ba_reserve_margin.csv directly, PSCo and WACM carry
# byte-for-byte identical reference_margin_pct for every year, so there's no real BA-differentiated
# reserve-margin data to preserve fidelity for.
MERGEABLE_CARRIERS = {"Solar:PV", "Wind", "Hydro", "Hydro:Pumped", "Storage:Battery"}


def aggregate_mergeable_resources(active: pd.DataFrame) -> pd.DataFrame:
    """Collapses MERGEABLE_CARRIERS rows into one aggregate per (Area, TechType[, wind point]),
    leaving every other row (Gas:CT/CC/IC/ST, Coal) completely untouched.

    Takes an already target_year-filtered `active` DataFrame (see build_existing_fleet_components)
    and returns one in the same column shape/dtypes, just with fewer rows -- every downstream
    calculation in build_existing_fleet_components (marginal_cost, capital_cost, p_min_pu, storage
    split) runs unmodified on the result, since the aggregate rows carry the same raw source
    columns real resources would, computed so those formulas reproduce the correct capacity-
    weighted values automatically:

      - MaxCap/MinCap/MaxStorage: summed (extensive quantities) -- this alone is what makes
        p_min_pu = MinCap/MaxCap and max_hours = MaxStorage/MaxCap come out capacity-weighted
        without any special-casing downstream.
      - EnCost/FixedRate: capacity-weighted average (intensive $/MWh, $/kW-yr quantities --
        summing would be wrong).
      - PaybckReq: the underlying round-trip efficiency (100/PaybckReq) is capacity-weighted
        averaged, then inverted back to a PaybckReq value -- PaybckReq itself is inverse-type, so
        averaging it directly would not reproduce the correct blended round-trip efficiency.
      - mincap_source: carried through unchanged (verified uniform within every merge group before
        this was implemented -- see build_plan.md).
      - accredited_capacity_pct: MaxCap-weighted average when members have Script 23
        values (Hydro / Hydro:Pumped). Solar:PV / Wind / Storage:Battery stay blank and
        take ELCC at reserve-margin solve time.
      - co2_RelRateMWh: 0. Constraint builders join this assembled table by Name, not
        the raw CSV, so aggregates must carry a rate (these carriers do not emit).
      - ba_code, CommissionDate, RetirementDate: dropped. Retirement filtering already happened in
        the caller before this function runs, so an aggregate never needs its own
        CommissionDate/RetirementDate; ba_code is dropped because this deliberately merges across
        BA (see MERGEABLE_CARRIERS comment above for why that's safe here).
    """
    mergeable = active[active["TechType"].isin(MERGEABLE_CARRIERS)].copy()
    individual = active[~active["TechType"].isin(MERGEABLE_CARRIERS)].copy()

    mergeable["wind_point"] = mergeable.apply(
        lambda row: parse_wind_point(row["Name"], row["Area"]) if row["TechType"] == "Wind" else None,
        axis=1,
    )

    rows = []
    for (area, tech, wind_point), group in mergeable.groupby(["Area", "TechType", "wind_point"], dropna=False):
        total_cap = group["MaxCap"].sum()
        round_trip = (100.0 / group["PaybckReq"] * group["MaxCap"]).sum() / total_cap if group["PaybckReq"].notna().any() else float("nan")

        # groupby's dropna=False preserves None as a group key, but the wind_point column itself
        # was upcast to float64 (mixing None with real ints), so it actually arrives here as NaN,
        # not None -- pd.isna() catches both.
        has_point = not pd.isna(wind_point)
        name = f"{area}_{tech}_pt{int(wind_point)}_agg" if has_point else f"{area}_{tech}_agg"
        if "accredited_capacity_pct" in group.columns:
            valid = group["accredited_capacity_pct"].notna()
            if valid.any():
                cap = group.loc[valid, "MaxCap"].sum()
                accredited = (
                    (group.loc[valid, "accredited_capacity_pct"] * group.loc[valid, "MaxCap"]).sum()
                    / cap
                )
            else:
                accredited = float("nan")
        else:
            accredited = float("nan")
        rows.append({
            "Name": name,
            "Area": area,
            "TechType": tech,
            "MaxCap": total_cap,
            "MinCap": group["MinCap"].sum(),
            "MaxStorage": group["MaxStorage"].sum() if group["MaxStorage"].notna().any() else float("nan"),
            "EnCost": (group["EnCost"] * group["MaxCap"]).sum() / total_cap,
            "FixedRate": (group["FixedRate"] * group["MaxCap"]).sum() / total_cap,
            "PaybckReq": 100.0 / round_trip,
            "mincap_source": group["mincap_source"].iloc[0],
            "Fuel": group["Fuel"].iloc[0],
            "ba_code": pd.NA,
            "CommissionDate": pd.NA,
            "RetirementDate": pd.NA,
            "accredited_capacity_pct": accredited,
            "co2_RelRateMWh": 0.0,
        })
    aggregated = pd.DataFrame(rows)

    return pd.concat([individual, aggregated], ignore_index=True)


def _wasteheat_name(val) -> str | None:
    if pd.isna(val):
        return None
    text = str(val).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _cap_weighted(values: pd.Series, weights: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    ok = v.notna() & w.notna() & (w > 0)
    if not ok.any():
        return float("nan")
    return float((v[ok] * w[ok]).sum() / w[ok].sum())


def aggregate_large_cc_blocks(active: pd.DataFrame, all_resources: pd.DataFrame) -> pd.DataFrame:
    """Collapse each WasteHeat-linked large CC (CTs + CA) into one Gas:CC row.

    Year filter has already run on unit rows. CA MW is scaled by remaining linked-CT
    MW / original linked-CT MW (original from the unfiltered CSV). CTs with no
    WasteHeat (Fort St. Vrain 5/6) stay individual. A CA with no remaining CT is a
    hard error. CTs whose CA is already retired stay individual (WHBypass simple-cycle).
    """
    if "WasteHeat" not in active.columns or "prime_mover" not in active.columns:
        return active

    original_ct_mw: dict[str, float] = {}
    for _, row in all_resources.iterrows():
        ca_name = _wasteheat_name(row.get("WasteHeat"))
        if ca_name is None:
            continue
        original_ct_mw[ca_name] = original_ct_mw.get(ca_name, 0.0) + float(row["MaxCap"])

    remaining_cts = []
    for _, row in active.iterrows():
        ca_name = _wasteheat_name(row.get("WasteHeat"))
        if ca_name is not None:
            remaining_cts.append((ca_name, row))
    cts_by_ca: dict[str, list] = {}
    for ca_name, row in remaining_cts:
        cts_by_ca.setdefault(ca_name, []).append(row)

    is_ca = active["prime_mover"].astype(str) == "CA"
    active_cas = active.loc[is_ca]
    for _, ca in active_cas.iterrows():
        ca_name = str(ca["Name"])
        if ca_name not in cts_by_ca:
            raise ValueError(
                f"Large-CC CA {ca_name} is active with no linked CTs remaining; "
                "align CA RetirementDate to the last linked CT (Script 19)."
            )

    drop_names: set[str] = set()
    merged_rows: list[dict] = []
    for _, ca in active_cas.iterrows():
        ca_name = str(ca["Name"])
        ct_rows = pd.DataFrame(cts_by_ca[ca_name])
        orig = original_ct_mw.get(ca_name, 0.0)
        if orig <= 0:
            raise ValueError(f"No original linked CT MW for CA {ca_name}")
        rem_ct_mw = float(ct_rows["MaxCap"].sum())
        scale = rem_ct_mw / orig
        ca_max = float(ca["MaxCap"]) * scale
        ca_min = float(ca["MinCap"]) * scale if pd.notna(ca["MinCap"]) else 0.0
        total_mw = rem_ct_mw + ca_max
        if total_mw <= 0:
            raise ValueError(f"Merged CC {ca_name}_cc has non-positive MW")

        ct_hr = pd.to_numeric(ct_rows["AvgHtRate"], errors="coerce")
        ct_co2 = pd.to_numeric(ct_rows["co2_RelRateMWh"], errors="coerce")
        ct_cap = pd.to_numeric(ct_rows["MaxCap"], errors="coerce")
        blended_hr = float((ct_hr * ct_cap).sum() / total_mw)
        blended_co2 = float((ct_co2 * ct_cap).sum() / total_mw)

        member_caps = pd.concat(
            [ct_cap.reset_index(drop=True), pd.Series([ca_max])],
            ignore_index=True,
        )
        member_encost = pd.concat(
            [pd.to_numeric(ct_rows["EnCost"], errors="coerce").reset_index(drop=True),
             pd.Series([ca["EnCost"]])],
            ignore_index=True,
        )
        member_fixed = pd.concat(
            [pd.to_numeric(ct_rows["FixedRate"], errors="coerce").reset_index(drop=True),
             pd.Series([ca["FixedRate"]])],
            ignore_index=True,
        )
        member_accr = pd.concat(
            [pd.to_numeric(ct_rows["accredited_capacity_pct"], errors="coerce").reset_index(drop=True),
             pd.Series([ca["accredited_capacity_pct"]])],
            ignore_index=True,
        )

        fuels = [str(v) for v in ct_rows["Fuel"].tolist() if pd.notna(v) and str(v).strip()]
        if not fuels:
            raise ValueError(f"Linked CTs for {ca_name} have no Fuel")
        if len(set(fuels)) != 1:
            raise ValueError(f"Linked CTs for {ca_name} have mixed Fuel: {set(fuels)}")

        row = ca.to_dict()
        row.update({
            "Name": f"{ca_name}_cc",
            "TechType": "Gas:CC",
            "MaxCap": total_mw,
            "MinCap": float(ct_rows["MinCap"].sum()) + ca_min,
            "EnCost": _cap_weighted(member_encost, member_caps),
            "FixedRate": _cap_weighted(member_fixed, member_caps),
            "accredited_capacity_pct": _cap_weighted(member_accr, member_caps),
            "AvgHtRate": blended_hr,
            "co2_RelRateMWh": blended_co2,
            "Fuel": fuels[0],
            "prime_mover": "CC",
            "WasteHeat": pd.NA,
            "WHBypass": pd.NA,
            "CommissionDate": pd.NA,
            "RetirementDate": pd.NA,
        })
        merged_rows.append(row)
        drop_names.add(ca_name)
        drop_names.update(ct_rows["Name"].astype(str).tolist())
        print(
            f"  large CC merge: {ca_name}_cc  {total_mw:.1f} MW  "
            f"(CT {rem_ct_mw:.1f} + CA {ca_max:.1f}, scale={scale:.3f})  "
            f"co2={blended_co2:.1f} lb/MWh  hr={blended_hr:.0f} Btu/kWh",
            flush=True,
        )

    leftover = active[~active["Name"].astype(str).isin(drop_names)].copy()
    merged = pd.DataFrame(merged_rows)
    return pd.concat([leftover, merged], ignore_index=True)


def active_existing_resources(year: int, *, aggregate_large_cc: bool = False) -> pd.DataFrame:
    """Year-filtered existing fleet after PyPSA aggregation. Index is not set.

    Constraint builders (CO2, RA) join this table by Name. Do not re-read
    colorado_resources.csv by network Name.
    """
    resources = pd.read_csv(RESOURCES_PATH)
    ref_date = pd.Timestamp(f"{year}-01-01")
    commission = pd.to_datetime(resources["CommissionDate"])
    retirement = pd.to_datetime(resources["RetirementDate"])
    active = resources[(commission <= ref_date) & (retirement > ref_date)].copy()
    active = aggregate_mergeable_resources(active)
    if aggregate_large_cc:
        active = aggregate_large_cc_blocks(active, resources)
    dups = active["Name"].duplicated()
    if dups.any():
        raise ValueError(
            f"Duplicate existing-fleet Names after assembly: "
            f"{active.loc[dups, 'Name'].tolist()}"
        )
    return active


def build_existing_fleet_components(
    target_year: int,
    *,
    aggregate_large_cc: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Existing colorado_resources.csv fleet -> PyPSA-ready Generator/StorageUnit specs.

    Returns (generators_df, storage_df), both indexed by resource Name, columns matching
    PyPSA's Generator/StorageUnit attribute names directly, ready for n.add("Generator",
    generators_df.index, **generators_df) once buses exist (Milestone 5). Fixed capacity only
    (p_nom_extendable=False).

    Pre-filtered to units operating during target_year: CommissionDate <= Jan 1 of target_year
    < RetirementDate. Milestone 6 still uses this per-year filter (then re-aggregates) rather
    than inventing a single build_year/lifetime for an aggregate row -- see
    foresight_approaches.md.

    marginal_cost = EnCost (variable O&M, $/MWh) + (AvgHtRate/1000 -> MMBtu/MWh) x fuel price
    ($/MMBtu, joined on Fuel + target_year -- each fuel_type maps to exactly one region in
    fuel_price_lookup.csv, e.g. natural_gas->Mountain, coal->National, so no region filter is
    needed here). Zero-fuel resources (Fuel is blank) get EnCost alone.

    capital_cost = FixedRate ($/kW-yr Fixed O&M) x 1000 -> $/MW-yr. Not sunk construction cost
    (colorado_resources.csv has no construction-cost column for existing plants) -- ongoing O&M
    only. Zero effect on this milestone's numbers since p_nom isn't a decision variable when
    fixed; included for realistic total-cost reporting.

    p_min_pu = MinCap / MaxCap (both resource-total since Script 17's 2026-08-14 fix), except
    forced to 0 whenever mincap_source == "must_run_maxcap" (Wind/Solar:PV/Solar:CSP) -- that
    EnCompass must-run convention doesn't mean "always at full output" the way PyPSA's p_min_pu
    would interpret MinCap=MaxCap; p_max_pu (the real CF profile, Milestone 1) should govern
    these resources entirely.

    Storage round-trip efficiency = 100/PaybckReq (verified against the actual data, 2026-08-15:
    batteries at PaybckReq=117.65 -> 85% RTE, exactly matching the candidate battery's ATB-sourced
    85%; pumped hydro at 125.00 -> 80% RTE, a sensible industry-typical figure) -- split
    symmetrically into efficiency_store/efficiency_dispatch via sqrt(round_trip) each way, same
    pattern as build_candidate_components()'s storage. Previously left at PyPSA's lossless
    default (1.0 each); fixed after being caught building the candidate-storage equivalent.

    MERGEABLE_CARRIERS (Solar:PV, Wind, Hydro, Hydro:Pumped, Storage:Battery) get aggregated one
    per (Area, TechType[, wind point]) via aggregate_mergeable_resources() before any of the above
    -- added 2026-08-17 once Milestone 5's first solve attempt showed the full 77-component fleet
    made the LP too large/slow. Gas:CT/CC/IC/ST and Coal stay individual unless
    aggregate_large_cc=True, which collapses each WasteHeat-linked large CC into one Gas:CC
    generator (Script 10 / 8b revision; default False so scripts 5-9 stay unit-level).
    """
    fuel_prices = pd.read_csv(FUEL_PRICE_PATH)
    active = active_existing_resources(target_year, aggregate_large_cc=aggregate_large_cc)

    fuel_year_prices = (
        fuel_prices.loc[fuel_prices["year"] == target_year]
        .set_index("fuel_type")["price_per_mmbtu"]
    )
    fuel_cost_per_mwh = active["Fuel"].map(fuel_year_prices) * (active["AvgHtRate"] / 1000.0)
    active["marginal_cost"] = active["EnCost"] + fuel_cost_per_mwh.fillna(0.0)

    active["capital_cost"] = active["FixedRate"] * 1000.0

    active["p_min_pu"] = active["MinCap"] / active["MaxCap"]
    active.loc[active["mincap_source"] == "must_run_maxcap", "p_min_pu"] = 0.0

    active["bus"] = active["Area"]
    active["carrier"] = active["TechType"]
    active["p_nom"] = active["MaxCap"]
    active["p_nom_extendable"] = False

    active = active.set_index("Name")
    is_storage = active["MaxStorage"].notna()

    generators_df = active.loc[~is_storage, GENERATOR_COLS].copy()

    storage_df = active.loc[is_storage, STORAGE_COLS[:-1]].copy()
    storage_df["max_hours"] = active.loc[is_storage, "MaxStorage"] / active.loc[is_storage, "MaxCap"]
    round_trip = 100.0 / active.loc[is_storage, "PaybckReq"]
    storage_df["efficiency_store"] = round_trip ** 0.5
    storage_df["efficiency_dispatch"] = round_trip ** 0.5

    return generators_df, storage_df


def build_candidate_components(
    target_year: int, *, hybrid_candidates: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Candidate technologies -> PyPSA-ready extendable Generator/StorageUnit specs.

    Returns (generators_df, storage_df), same shape/convention as
    build_existing_fleet_components(). One instance per technology x allowed_zones entry
    (p_nom_extendable=True, p_nom=0 -- no capacity exists yet), except Wind: one instance per
    zone x wind CF point (WIND_ZONE_POINTS -- East's 3 siting points stay separate, not
    averaged). Solar+Storage is excluded by default -- see EXCLUDED_CANDIDATE_TECHS.
    hybrid_candidates=True drops that exclusion and emits a paired Generator + StorageUnit
    per zone (Milestone 8c; pypsa/_plans/milestone_8c_hybrid_solar_storage.md).

    capital_cost = (occ_per_kw x 1000 x crf) + (fixed_om_per_kw_yr x 1000) -- construction
    financing and fixed O&M combined, since PyPSA has no separate slot for the two (same
    reasoning as the existing fleet's capital_cost). Both come from atb_candidate_lookup.csv at
    target_year; crf is ATB-published for most technologies, computed via the verified real-WACC
    formula for Gas:CT/Gas:CC/Solar+Storage (Script 20, 2026-08-15) where ATB doesn't publish one.
    Hybrid cost sits entirely on the solar Generator (ATB $/kW-AC of the 100 MWAC plant);
    the paired battery has capital_cost=0 and fom_cost=0.

    marginal_cost = variable_om_per_mwh + heat_rate_mmbtu_per_mwh x fuel price, fuel price joined
    on Fuel + target_year (same fuel_price_lookup.csv join as the existing fleet -- each fuel
    type maps to exactly one region, no region filter needed). Zero-fuel technologies
    (candidate_technology_parameters.csv's Fuel is blank) use variable_om_per_mwh alone.

    p_min_pu = min_stable_pct / 100 -- candidate_technology_parameters.csv stores this 0-100, not
    PyPSA's 0-1 fraction. 0 for technologies with no minimum-stable-level entry (all non-thermal
    candidates: Solar:PV, Wind, Storage:Battery, Solar+Storage solar half).

    Storage split (Storage:Battery, and the hybrid battery half when hybrid_candidates):
    max_hours = storage_duration_hours directly (already in hours, no conversion). Round-trip
    efficiency (round_trip_efficiency_pct) is split symmetrically into PyPSA's separate
    efficiency_store/efficiency_dispatch via sqrt(round_trip) each way, so store-then-dispatch
    compounds back to the published round-trip figure. Do not send the Solar+Storage row down
    this path alone -- that is the fake extra battery 8c exists to avoid.

    lifetime_years is passed through from candidate_technology_parameters.csv (needed by
    Milestone 6's vintage carry-forward). fom_cost is the Fixed O&M slice of capital_cost
    (fixed_om_per_kw_yr x 1000) so a carried vintage can be charged FOM only, not a second
    construction annuity. Neither column is a PyPSA component attribute -- callers must drop
    them before n.add.
    """
    excluded = set(EXCLUDED_CANDIDATE_TECHS)
    if hybrid_candidates:
        excluded.discard(HYBRID_CARRIER)

    candidates = pd.read_csv(CANDIDATE_PARAMS_PATH)
    candidates = candidates[~candidates["tech_class"].isin(excluded)]

    atb = pd.read_csv(ATB_LOOKUP_PATH)
    atb_year = atb.loc[
        (atb["atb_year"] == target_year) & (atb["scenario"] == ATB_SCENARIO)
    ].set_index("tech_class")

    fuel_prices = pd.read_csv(FUEL_PRICE_PATH)
    fuel_year_prices = (
        fuel_prices.loc[fuel_prices["year"] == target_year]
        .set_index("fuel_type")["price_per_mmbtu"]
    )

    rows = []
    for _, tech_row in candidates.iterrows():
        tech = tech_row["tech_class"]
        atb_row = atb_year.loc[tech]

        fom_cost = atb_row["fixed_om_per_kw_yr"] * 1000.0
        capital_cost = atb_row["occ_per_kw"] * 1000.0 * atb_row["crf"] + fom_cost

        fuel = tech_row["Fuel"]
        if pd.notna(fuel):
            fuel_price = fuel_year_prices.get(fuel, 0.0)
            fuel_cost_per_mwh = fuel_price * atb_row["heat_rate_mmbtu_per_mwh"]
        else:
            fuel_cost_per_mwh = 0.0
        vom = atb_row["variable_om_per_mwh"] if pd.notna(atb_row["variable_om_per_mwh"]) else 0.0
        marginal_cost = vom + fuel_cost_per_mwh

        p_min_pu = (tech_row["min_stable_pct"] / 100.0) if pd.notna(tech_row["min_stable_pct"]) else 0.0

        zones = ALL_ZONES if tech_row["allowed_zones"] == "All" else [
            z.strip() for z in tech_row["allowed_zones"].split(",")
        ]

        for zone in zones:
            points = WIND_ZONE_POINTS.get(zone, [None]) if tech == "Wind" else [None]
            for pt in points:
                name = f"Candidate_{tech}_{zone}" + (f"_pt{pt}" if pt is not None else "")
                if tech == HYBRID_CARRIER:
                    # Solar half: full bundled cost, no storage_duration so it stays a Generator.
                    rows.append({
                        "name": name,
                        "bus": zone,
                        "carrier": tech,
                        "p_nom": 0.0,
                        "p_nom_extendable": True,
                        "marginal_cost": marginal_cost,
                        "capital_cost": capital_cost,
                        "p_min_pu": p_min_pu,
                        "lifetime_years": tech_row["lifetime_years"],
                        "fom_cost": fom_cost,
                        "storage_duration_hours": float("nan"),
                        "round_trip_efficiency_pct": float("nan"),
                    })
                    # Battery half: cost is on solar; duration/RTE from this tech row.
                    rows.append({
                        "name": name + HYBRID_BATTERY_SUFFIX,
                        "bus": zone,
                        "carrier": tech,
                        "p_nom": 0.0,
                        "p_nom_extendable": True,
                        "marginal_cost": 0.0,
                        "capital_cost": 0.0,
                        "p_min_pu": 0.0,
                        "lifetime_years": tech_row["lifetime_years"],
                        "fom_cost": 0.0,
                        "storage_duration_hours": tech_row["storage_duration_hours"],
                        "round_trip_efficiency_pct": tech_row["round_trip_efficiency_pct"],
                    })
                    continue
                rows.append({
                    "name": name,
                    "bus": zone,
                    "carrier": tech,
                    "p_nom": 0.0,
                    "p_nom_extendable": True,
                    "marginal_cost": marginal_cost,
                    "capital_cost": capital_cost,
                    "p_min_pu": p_min_pu,
                    "lifetime_years": tech_row["lifetime_years"],
                    "fom_cost": fom_cost,
                    "storage_duration_hours": tech_row["storage_duration_hours"],
                    "round_trip_efficiency_pct": tech_row["round_trip_efficiency_pct"],
                })

    df = pd.DataFrame(rows).set_index("name")
    is_storage = df["storage_duration_hours"].notna()

    extra_cols = ["lifetime_years", "fom_cost"]
    generators_df = df.loc[~is_storage, GENERATOR_COLS + extra_cols].copy()

    storage_df = df.loc[is_storage, ["bus", "carrier", "p_nom", "p_nom_extendable", "marginal_cost", "capital_cost"] + extra_cols].copy()
    storage_df["max_hours"] = df.loc[is_storage, "storage_duration_hours"]
    round_trip = df.loc[is_storage, "round_trip_efficiency_pct"] / 100.0
    storage_df["efficiency_store"] = round_trip ** 0.5
    storage_df["efficiency_dispatch"] = round_trip ** 0.5

    return generators_df, storage_df


def main() -> None:
    print("\n--- PyPSA Milestone 4: existing fleet assembly ---")

    test_year = 2035
    print(f"\nBuilding existing fleet components for target_year={test_year} (placeholder pilot year)...")
    generators_df, storage_df = build_existing_fleet_components(test_year)

    all_resources = pd.read_csv(RESOURCES_PATH)
    print(f"\nTotal resources in colorado_resources.csv: {len(all_resources)}")
    print(f"Active at {test_year}: {len(generators_df) + len(storage_df)} "
          f"({len(generators_df)} generators, {len(storage_df)} storage)")

    print("\n--- Sanity checks ---")

    # Fuel populated but heat rate missing would silently zero out a real fuel cost via fillna(0)
    fueled_no_htrate = all_resources[all_resources["Fuel"].notna() & all_resources["AvgHtRate"].isna()]
    print(f"Resources with Fuel set but AvgHtRate missing (would silently drop fuel cost): "
          f"{len(fueled_no_htrate)}")
    if len(fueled_no_htrate):
        print(fueled_no_htrate[["Name", "Fuel", "AvgHtRate"]].to_string(index=False))

    # p_min_pu should be 0 for every must-run resource -- checked by carrier (Solar:PV/Wind are
    # always must-run) rather than by matching against all_resources' raw individual names, since
    # aggregation means generators_df.index no longer contains those names at all.
    must_run_carriers = generators_df["carrier"].isin(["Solar:PV", "Wind"])
    bad = generators_df.loc[must_run_carriers & (generators_df["p_min_pu"] != 0.0)]
    print(f"Must-run generators (Solar:PV/Wind) with p_min_pu != 0 (should be empty): {len(bad)}")
    if len(bad):
        print(bad.to_string())

    print(f"\nDenver_PSCO_GasCC_small p_min_pu (expect ~0.225, matching the earlier hand-check):")
    if "Denver_PSCO_GasCC_small" in generators_df.index:
        print(f"  {generators_df.loc['Denver_PSCO_GasCC_small', 'p_min_pu']:.4f}")
    else:
        print("  (not active in this target_year)")

    # Individual "4hr"/"2hr"-named batteries no longer exist post-aggregation -- print max_hours
    # for every storage row directly instead of matching on a name substring that's now gone.
    print(f"\nAll storage max_hours (aggregated where applicable):")
    for name in storage_df.index:
        print(f"  {name:<40} {storage_df.loc[name, 'max_hours']:.2f}")

    print(f"\nStorage round-trip efficiency (efficiency_store x efficiency_dispatch) -- "
          f"batteries should be ~85%, pumped hydro ~80%:")
    for name in storage_df.index:
        row = storage_df.loc[name]
        rt = row["efficiency_store"] * row["efficiency_dispatch"]
        print(f"  {name:<55} {rt:.1%}")

    print(f"\nSample generator rows:")
    print(generators_df.head(5).to_string())
    print(f"\nSample storage rows:")
    print(storage_df.to_string())

    print(f"\nSaving inspection checkpoints to {OUT_DIR.relative_to(PROJECT_ROOT)}...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generators_df.to_csv(OUT_DIR / f"existing_fleet_generators_{test_year}.csv")
    storage_df.to_csv(OUT_DIR / f"existing_fleet_storage_{test_year}.csv")
    print(f"  existing_fleet_generators_{test_year}.csv")
    print(f"  existing_fleet_storage_{test_year}.csv")

    print("\n--- PyPSA Milestone 4: candidate technology assembly ---")

    print(f"\nBuilding candidate components for target_year={test_year}...")
    cand_generators_df, cand_storage_df = build_candidate_components(test_year)

    all_candidates = pd.read_csv(CANDIDATE_PARAMS_PATH)
    print(f"\nCandidate tech_classes in source: {len(all_candidates)} "
          f"({', '.join(all_candidates['tech_class'])})")
    print(f"Excluded: {sorted(EXCLUDED_CANDIDATE_TECHS)}")
    print(f"Instances built: {len(cand_generators_df) + len(cand_storage_df)} "
          f"({len(cand_generators_df)} generator, {len(cand_storage_df)} storage)")

    print("\n--- Sanity checks ---")

    # Wind should be 3 instances in East, 1 each in North/South = 5 total, not a flat
    # 3-zones-x-1-instance count.
    wind_names = [n for n in cand_generators_df.index if n.startswith("Candidate_Wind_")]
    print(f"\nWind candidate instances ({len(wind_names)}, expect 5 -- East x3, North x1, South x1):")
    for n in sorted(wind_names):
        print(f"  {n}: bus={cand_generators_df.loc[n, 'bus']}")

    # Every non-Wind tech with allowed_zones="All" should produce exactly 6 instances (one per
    # zone); Solar+Storage should produce none at all (excluded).
    print(f"\nInstance count by technology (Wind excluded from this check -- see above):")
    all_built = pd.concat([cand_generators_df, cand_storage_df])
    for tech in all_candidates["tech_class"]:
        if tech in EXCLUDED_CANDIDATE_TECHS or tech == "Wind":
            continue
        n = (all_built["carrier"] == tech).sum()
        print(f"  {tech:<18} {n} instances (expect 6, allowed_zones=All)")
    n_hybrid = (all_built["carrier"] == HYBRID_CARRIER).sum()
    print(f"  {HYBRID_CARRIER:<18} {n_hybrid} instances (expect 0, excluded)")

    # Spot-check capital_cost/marginal_cost against atb_candidate_lookup.csv directly.
    atb = pd.read_csv(ATB_LOOKUP_PATH)
    atb_row = atb.loc[(atb["atb_year"] == test_year) & (atb["scenario"] == "Moderate")].set_index("tech_class")
    print(f"\nSpot-check capital_cost against atb_candidate_lookup.csv directly ({test_year}):")
    for tech in ["Solar:PV", "Gas:CC", "Storage:Battery"]:
        r = atb_row.loc[tech]
        expected = r["occ_per_kw"] * 1000.0 * r["crf"] + r["fixed_om_per_kw_yr"] * 1000.0
        any_name = all_built[all_built["carrier"] == tech].index[0]
        actual = all_built.loc[any_name, "capital_cost"]
        match = "OK" if abs(actual - expected) < 0.01 else "MISMATCH"
        print(f"  {tech:<18} expected=${expected:,.2f}/MW-yr  actual=${actual:,.2f}/MW-yr  [{match}]")

    print(f"\nSample candidate generator rows:")
    print(cand_generators_df.to_string())
    print(f"\nCandidate storage rows:")
    print(cand_storage_df.to_string())

    print(f"\nSaving inspection checkpoints...")
    cand_generators_df.to_csv(OUT_DIR / f"candidates_generators_{test_year}.csv")
    cand_storage_df.to_csv(OUT_DIR / f"candidates_storage_{test_year}.csv")
    print(f"  candidates_generators_{test_year}.csv")
    print(f"  candidates_storage_{test_year}.csv")

    print("\n--- PyPSA Milestone 8c: hybrid_candidates=True ---")
    hy_gen, hy_sto = build_candidate_components(test_year, hybrid_candidates=True)
    n_hy_gen = (hy_gen["carrier"] == HYBRID_CARRIER).sum()
    n_hy_sto = (hy_sto["carrier"] == HYBRID_CARRIER).sum()
    print(f"  {HYBRID_CARRIER} generators {n_hy_gen} (expect 6)")
    print(f"  {HYBRID_CARRIER} storage    {n_hy_sto} (expect 6)")
    r_h = atb_row.loc[HYBRID_CARRIER]
    expected_h = r_h["occ_per_kw"] * 1000.0 * r_h["crf"] + r_h["fixed_om_per_kw_yr"] * 1000.0
    hy_g = hy_gen[hy_gen["carrier"] == HYBRID_CARRIER]
    hy_s = hy_sto[hy_sto["carrier"] == HYBRID_CARRIER]
    actual_g = float(hy_g["capital_cost"].iloc[0])
    actual_s = float(hy_s["capital_cost"].iloc[0])
    match_g = "OK" if abs(actual_g - expected_h) < 0.01 else "MISMATCH"
    match_s = "OK" if abs(actual_s) < 0.01 else "MISMATCH"
    print(
        f"  solar capital_cost expected=${expected_h:,.2f}/MW-yr  "
        f"actual=${actual_g:,.2f}/MW-yr  [{match_g}]"
    )
    print(f"  battery capital_cost expected=$0.00/MW-yr  actual=${actual_s:,.2f}/MW-yr  [{match_s}]")
    for zone in ALL_ZONES:
        solar = f"Candidate_{HYBRID_CARRIER}_{zone}"
        batt = solar + HYBRID_BATTERY_SUFFIX
        if solar not in hy_gen.index or batt not in hy_sto.index:
            print(f"  MISSING pair: {solar} / {batt}")
        else:
            print(f"  {solar} + {batt}")


if __name__ == "__main__":
    main()
