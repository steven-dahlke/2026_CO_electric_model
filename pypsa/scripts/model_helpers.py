"""
Shared building blocks for pypsa/scripts/.

Per pypsa/Documentation/build_plan.md's code-organization decision: extracted on first actual
duplication, not speculatively up front. WIND_ZONE_POINTS / parse_wind_point / resolve_cf_column
were the first extractions. build_network / make_week_cyclic_soc moved here for Milestone 6
(second caller of the Milestone 5 year-builder). The myopic vintage/solve loop moved here for
Milestone 7a (second caller of the Milestone 6 sequence). Topology is two booleans
(internal_limits, neighbors); energy Links use raw_sum_mw, firm N-1 is 8a2 RA pipes.
Live paper cases use run_scenarios.py; construction callers live in _dev_milestones/.

Public names by section (not alphabetical -- keep make_*/print_* pairs together):
  CF column resolution: parse_wind_point, resolve_cf_column, WIND_ZONE_POINTS
  Week-cyclic SOC: make_week_cyclic_soc
  Network assembly: build_network, UNCONSTRAINED_LINK_MW
  Myopic vintages: surviving_vintages, harvest_vintages
  Reporting: capacity_records, print_buildout_table, generation_by_carrier,
    storage_charge_by_carrier, print_soc_check,
    print_net_interchange, gross_interchange_by_market, cost_of_year,
    npv_from_cost_table, dispatch_table,
    write_cost_dispatch_from_checkpoints, write_storage_charge_from_checkpoints,
    write_gross_interchange_from_checkpoints,
    run_output_dir, run_checkpoint_path,
    run_capacity_csv_path, run_solve_log_path, tee_solve_log
  HiGHS: highs_simplex_year_banner, compose_extra_functionality
  Resource adequacy: coincident_peak_zonal_loads, statewide_coincident_peak, statewide_prm_pct,
    accredited_fractions, make_reserve_margin, print_reserve_margin_table, make_zonal_ra_pipes,
    print_zonal_ra_table
  CO2 cap: annual_co2_cap_mmt, emissions_rate_lb_per_mwh, make_co2_cap, print_co2_table
  Hybrids: HYBRID_CARRIER, make_hybrid_pairing, hybrid_solar_name_for_battery,
    hybrid_battery_name_for_solar
  Myopic solve loop: optimize_highs, run_myopic_sequence
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import re
import sys
import threading
import time
from datetime import datetime

import pandas as pd

# 01/03/04 import names from this module. Import those scripts only inside
# build_network so running 01/03/04 as __main__ does not circular-import a
# half-initialized model_helpers.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_SCRIPTS_DIR))


def _import_installed_pypsa():
    """Load the PyPSA library, not this repo's pypsa/ docs-and-scripts folder."""
    existing = sys.modules.get("pypsa")
    if existing is not None and hasattr(existing, "Network"):
        return existing
    repo_pypsa = os.path.dirname(_SCRIPTS_DIR)
    blocked = {os.path.abspath(_PROJECT_ROOT), os.path.abspath(repo_pypsa)}
    cwd = os.getcwd()
    cleaned = []
    for p in sys.path:
        resolved = os.path.abspath(p if p else cwd)
        if resolved not in blocked:
            cleaned.append(p)
    old_path = sys.path
    sys.path = cleaned
    try:
        for key in [k for k in sys.modules if k == "pypsa" or k.startswith("pypsa.")]:
            if not hasattr(sys.modules[key], "Network"):
                del sys.modules[key]
        import pypsa as installed
        return installed
    finally:
        sys.path = old_path


pypsa = _import_installed_pypsa()

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from utils import find_project_root

PROJECT_ROOT = find_project_root()
ZONES_DIR = PROJECT_ROOT / "data_cleaning" / "zones"
ZONE_BA_MAP_PATH = ZONES_DIR / "zone_ba_map.csv"
TRANSFER_LIMITS_PATH = ZONES_DIR / "zone_transfer_limits.csv"
BA_RESERVE_MARGIN_PATH = ZONES_DIR / "ba_reserve_margin.csv"
RESOURCES_PATH = PROJECT_ROOT / "data_cleaning" / "resources" / "colorado_resources.csv"
CANDIDATE_PARAMS_PATH = (
    PROJECT_ROOT / "data_cleaning" / "resources" / "candidate_technology_parameters.csv"
)
ELCC_LOOKUP_PATH = PROJECT_ROOT / "data_cleaning" / "resources" / "elcc" / "elcc_lookup.csv"
CO2_TARGET_PATH = PROJECT_ROOT / "data_cleaning" / "policy" / "co2_target.csv"
CO2_PATHS_DIR = PROJECT_ROOT / "data_cleaning" / "policy" / "co2_paths"

ELCC_CARRIERS = frozenset({"Solar:PV", "Wind", "Storage:Battery"})
CO2_BASELINE_2005_MMT = 42.023
LB_PER_METRIC_TON = 2204.6226218488
CO2_IMPORT_FLOW = "CO2_import_flow"
CO2_CONSTRAINT = "co2_CO"

# Still far above any plausible zonal transfer (Colorado statewide peak is ~10 GW). Same
# unconstrained stand-in Milestone 5 used; internal_limits=False keeps this magnitude.
UNCONSTRAINED_LINK_MW = 20_000.0
IMPORT_CARRIER = "import"
# Derived from the transfer-limits CSV itself (sorted for a fixed, deterministic order) rather
# than hardcoded, so there is one source of truth instead of a literal plus a validation check
# guarding against it drifting from the CSV. Order doesn't need to match any specific convention,
# just be consistent -- _add_external_market_generators() reindexes/zips positionally against
# this same tuple, so any single deterministic ordering works.
EXPECTED_EXTERNAL_BUSES = tuple(
    sorted(
        pd.read_csv(TRANSFER_LIMITS_PATH)
        .pipe(lambda df: df.loc[df["boundary_type"] == "external", "to_zone"])
        .unique()
    )
)
# Script 25 N-1 zeros: single-circuit internals, firm TTC = 0. Real ties; energy Links
# still have raw_sum_mw. Pairs are stored unordered as (from_zone, to_zone) in the CSV.
ZERO_FIRM_PAIRS = frozenset({("North", "West"), ("Mountain", "North")})

INVESTMENT_YEARS = [2030, 2035, 2040, 2045, 2050]
P_NOM_OPT_MIN = 0.01
NPV_DISCOUNT_RATE = 0.03
NPV_BASE_YEAR = 2030
NPV_STEP_YEARS = 5
ATB_LOOKUP_PATH = (
    PROJECT_ROOT / "data_cleaning" / "resources" / "costs" / "atb" / "atb_candidate_lookup.csv"
)
ATB_SCENARIO = "Moderate"
COST_IDENTITY_TOL = 10.0
DISPATCH_GWH_TOL = 1e-4
COST_CSV_COLS = [
    "year",
    "capex_overnight",
    "fom_existing",
    "fom_vintage",
    "fom_new",
    "opex_instate",
    "import_cost",
    "export_revenue",
    "annual_system_cost",
    "annual_system_cost_ex_trade",
    "lp_objective",
]

# Milestone 8c hybrid solar+storage. ATB 2024 PV-Plus-Battery default: 60 MW usable
# 4-hour battery per 100 MWAC solar. See pypsa/_plans/milestone_8c_hybrid_solar_storage.md.
HYBRID_CARRIER = "Solar+Storage"
HYBRID_BATTERY_SUFFIX = "_Battery"
HYBRID_BATTERY_MW_PER_SOLAR_MW = 0.6

# Columns n.add accepts. Candidate frames also carry lifetime_years / fom_cost for Milestone 6
# vintage carry-forward -- those must be stripped before add.
PYPSA_GENERATOR_ATTRS = [
    "bus", "carrier", "p_nom", "p_nom_extendable", "marginal_cost", "capital_cost", "p_min_pu",
]
PYPSA_STORAGE_ATTRS = [
    "bus", "carrier", "p_nom", "p_nom_extendable", "marginal_cost", "capital_cost",
    "max_hours", "efficiency_store", "efficiency_dispatch",
]

# East zone has 3 distinct wind siting points (not averaged -- see [[project_east_wind_points]]);
# North and South each have 1. Matches the calibrated wind CF file's column structure
# (wind_cf_calibrated.csv: East_2018_wind_point1/2/3_cf, North_2018_wind_point1_cf,
# South_2018_wind_point1_cf) and candidate_technology_parameters.csv's Wind allowed_zones
# ("East,North,South"). Used by both 01_timeseries_assembly.py (CF column naming) and
# 04_resource_assembly.py (candidate wind siting).
WIND_ZONE_POINTS: dict[str, list[int]] = {
    "East": [1, 2, 3],
    "North": [1],
    "South": [1],
}

_WIND_POINT_RE = re.compile(r"_pt(\d+)")


# --- CF column resolution ---

def parse_wind_point(name: str, bus: str) -> int:
    """Extracts a Wind resource's siting point number from its name, defaulting to 1 when absent.

    Third shared extraction (added during Milestone 5's build) -- needed identically by
    resolve_cf_column() below and by the existing-fleet aggregation logic in
    04_resource_assembly.py. East's existing wind
    resources are individually named with a "_pt1/_pt2/_pt3" infix (e.g.
    "East_Wind_pt1_PSCO_existing"); candidates already encode this as a name suffix (e.g.
    "Candidate_Wind_East_pt1") -- the same regex search over the whole name handles both. Zones
    with only one wind point (North/South) have no "_pt" in their existing resource names at all,
    hence the default to point 1 when the regex finds nothing.
    """
    match = _WIND_POINT_RE.search(name)
    point = int(match.group(1)) if match else 1
    if point not in WIND_ZONE_POINTS.get(bus, []):
        raise ValueError(f"{name}: resolved wind point {point} is not valid for zone {bus}")
    return point


def resolve_cf_column(name: str, carrier: str, bus: str) -> str | None:
    """Maps a generator (existing-fleet or candidate) to its build_cf_timeseries() column, or
    None if this carrier has no CF profile (thermal/storage/nuclear/geothermal/hydro correctly
    fall through to PyPSA's default p_max_pu=1 -- no entry needed for those).
    """
    if carrier == "Solar:PV" or carrier == HYBRID_CARRIER:
        return f"{bus}_solar_cf"
    if carrier == "Wind":
        return f"{bus}_wind_pt{parse_wind_point(name, bus)}_cf"
    return None


def hybrid_solar_name_for_battery(storage_name: str) -> str:
    """Candidate_..._Battery -> Candidate_...; Built_..._Battery_YYYY -> Built_..._YYYY."""
    name = str(storage_name)
    if name.endswith(HYBRID_BATTERY_SUFFIX):
        return name[: -len(HYBRID_BATTERY_SUFFIX)]
    prefix, year = name.rsplit("_", 1)
    if year.isdigit() and prefix.endswith(HYBRID_BATTERY_SUFFIX):
        return prefix[: -len(HYBRID_BATTERY_SUFFIX)] + "_" + year
    raise ValueError(f"Cannot parse hybrid solar name from {name!r}")


def hybrid_battery_name_for_solar(solar_name: str) -> str:
    """Inverse of hybrid_solar_name_for_battery."""
    name = str(solar_name)
    prefix, maybe_year = name.rsplit("_", 1)
    if maybe_year.isdigit() and name.startswith("Built_"):
        return f"{prefix}{HYBRID_BATTERY_SUFFIX}_{maybe_year}"
    return name + HYBRID_BATTERY_SUFFIX


# --- Week-cyclic SOC ---

def make_week_cyclic_soc(periods):
    """Return extra_functionality that wraps StorageUnit SOC within each representative week.

    `periods` is the list of (week_snapshots, weight) from select_representative_periods(...,
    return_periods=True) -- real per-period boundaries, including a possible short year-end
    period, so we must not re-derive them by assuming a fixed 168-hour stride.
    """

    def extra_functionality(n, snapshots):
        if n.storage_units.empty:
            return
        m = n.model
        balance_name = "StorageUnit-energy_balance"
        if balance_name not in m.constraints:
            return

        start_index = pd.DatetimeIndex([week[0] for week, _ in periods])
        # labels == -1 is linopy's inactive-constraint sentinel (same as a False mask at
        # creation). Dropping the default period-start rows is required: adding a wrap equality
        # *on top* would still leave March's last hour feeding July's first hour.
        m.constraints[balance_name].data["labels"].loc[dict(snapshot=start_index)] = -1

        soc = m["StorageUnit-state_of_charge"]
        p_dispatch = m["StorageUnit-p_dispatch"]
        p_store = m["StorageUnit-p_store"]
        su = n.storage_units
        stores_w = n.snapshot_weightings["stores"]
        standing_loss = (
            su["standing_loss"] if "standing_loss" in su.columns
            else pd.Series(0.0, index=su.index)
        )
        has_spill = "StorageUnit-spill" in m.variables

        for i, (week, _) in enumerate(periods):
            first, last = week[0], week[-1]
            eh = float(stores_w.loc[first])
            eff_stand = (1.0 - standing_loss) ** eh
            # Energy balance at the week's first hour, with "previous" = last hour of *this*
            # week: soc[first] = soc[last] * eff_stand + store*eff_store*eh
            #                   - dispatch/eff_dispatch*eh  (inflow is zero for this fleet).
            lhs = (
                -soc.sel(snapshot=first)
                + soc.sel(snapshot=last) * eff_stand.to_numpy()
                + p_store.sel(snapshot=first) * (su["efficiency_store"] * eh).to_numpy()
                - p_dispatch.sel(snapshot=first) * (eh / su["efficiency_dispatch"]).to_numpy()
            )
            if has_spill:
                lhs = lhs - m["StorageUnit-spill"].sel(snapshot=first) * eh
            m.add_constraints(lhs == 0, name=f"StorageUnit-energy_balance-week{i}-wrap")

    return extra_functionality


# --- Network assembly ---

def _pypsa_attrs(df: pd.DataFrame, attrs: list[str]) -> dict:
    """kwargs for n.add, only columns PyPSA knows about (and that this frame actually has)."""
    present = [c for c in attrs if c in df.columns]
    return {c: df[c] for c in present}


def _raw_p_nom(pairs: pd.DataFrame, kind: str) -> pd.Series:
    """raw_sum_mw as Link p_nom. Reject NaN / non-positive (N-1 zeros stay on transfer_limit_mw)."""
    if "raw_sum_mw" not in pairs.columns:
        raise ValueError(f"{TRANSFER_LIMITS_PATH} has no raw_sum_mw column")
    p_nom = pairs["raw_sum_mw"].astype(float)
    if p_nom.isna().any():
        bad = pairs.loc[p_nom.isna(), ["from_zone", "to_zone"]]
        raise ValueError(f"raw_sum_mw is NaN for {kind} pairs:\n{bad}")
    if (p_nom <= 0).any():
        bad = pairs.loc[p_nom <= 0, ["from_zone", "to_zone", "raw_sum_mw"]]
        raise ValueError(
            f"{kind} requires positive raw_sum_mw on every pair "
            f"(single-circuit N-1 zeros belong on transfer_limit_mw, not here):\n{bad}"
        )
    return p_nom


def _add_zone_links(n, pairs: pd.DataFrame, p_nom: pd.Series, mode_label: str) -> None:
    link_names = [f"Link_{row.from_zone}_{row.to_zone}" for row in pairs.itertuples()]
    n.add(
        "Link",
        link_names,
        bus0=pairs["from_zone"].values,
        bus1=pairs["to_zone"].values,
        p_nom=p_nom.to_numpy(),
        p_min_pu=-1.0,
        marginal_cost=0.0,
    )
    print(f"  {len(link_names)} links, {mode_label}, bidirectional")
    for name, row, mw in zip(link_names, pairs.itertuples(), p_nom):
        print(f"    {name}: {row.from_zone} <-> {row.to_zone}  p_nom={mw:,.1f} MW")


def _external_rows(limits: pd.DataFrame) -> pd.DataFrame:
    external = limits[limits["boundary_type"] == "external"].copy()
    if external.empty:
        raise ValueError(f"No external rows in {TRANSFER_LIMITS_PATH}")
    co_zones = set(pd.read_csv(ZONE_BA_MAP_PATH)["zone"])
    bad_from = set(external["from_zone"]) - co_zones
    if bad_from:
        raise ValueError(f"external from_zone not a CO zone: {sorted(bad_from)}")
    spilled = set(external["to_zone"]) & co_zones
    if spilled:
        raise ValueError(f"external to_zone collides with a CO zone: {sorted(spilled)}")
    return external


def _add_external_market_generators(n, external: pd.DataFrame, cand_gen: pd.DataFrame) -> None:
    """Energy-only market on each external bus, priced at that year's Candidate_Gas:CC MC."""
    cc = cand_gen.loc[cand_gen["carrier"] == "Gas:CC", "marginal_cost"]
    if cc.empty:
        raise ValueError("Candidate Gas:CC missing; cannot price external markets")
    unique = pd.unique(cc.to_numpy())
    if len(unique) != 1:
        raise ValueError(f"Candidate Gas:CC marginal_cost not unique: {unique}")
    cc_mc = float(unique[0])

    p_nom_by_bus = (
        external.groupby("to_zone")["raw_sum_mw"].sum().astype(float)
        .reindex(list(EXPECTED_EXTERNAL_BUSES))
    )
    if p_nom_by_bus.isna().any():
        raise ValueError(
            f"missing incident Link p_nom for {p_nom_by_bus[p_nom_by_bus.isna()].index.tolist()}"
        )

    names = [f"Market_{bus}" for bus in EXPECTED_EXTERNAL_BUSES]
    n.add(
        "Generator",
        names,
        bus=list(EXPECTED_EXTERNAL_BUSES),
        carrier=IMPORT_CARRIER,
        p_nom=p_nom_by_bus.to_numpy(),
        p_nom_extendable=False,
        p_min_pu=-1.0,
        capital_cost=0.0,
        marginal_cost=cc_mc,
    )
    print(f"  {len(names)} market generators at Candidate_Gas:CC MC = ${cc_mc:.2f}/MWh")
    for name, bus in zip(names, EXPECTED_EXTERNAL_BUSES):
        print(f"    {name}: bus={bus}  p_nom={p_nom_by_bus[bus]:,.1f} MW")


def _relax_instate_generator_pmin(
    n,
    generators: pd.DataFrame | None = None,
    *,
    log: bool = False,
) -> None:
    """Zero p_min_pu on in-state Generators. Market_* stay at -1. StorageUnits untouched.

    Expansion cycling: hourly p >= Pmin would mean cannot shut down. True on/off+Pmin is
    operational MILP (Milestone 9). See pypsa/_plans/milestone_8b_co2_cap.md.
    """
    instate = n.generators["carrier"] != IMPORT_CARRIER
    pmin = n.generators["p_min_pu"].copy()
    pmin.loc[instate] = 0.0
    n.generators["p_min_pu"] = pmin
    if generators is not None and len(generators) and "p_min_pu" in generators.columns:
        generators["p_min_pu"] = 0.0
    if log:
        n_mkt = int((~instate).sum())
        print(
            f"  relax_pmin: p_min_pu=0 on {int(instate.sum())} in-state generators "
            f"({n_mkt} Market_* kept at p_min_pu=-1)",
            flush=True,
        )


def build_network(
    target_year: int,
    extra_fixed_generators: pd.DataFrame | None = None,
    extra_fixed_storage: pd.DataFrame | None = None,
    internal_limits: bool = True,
    neighbors: bool = True,
    relax_pmin: bool = True,
    aggregate_large_cc: bool = True,
    hybrid_candidates: bool = True,
) -> tuple[pypsa.Network, pd.DataFrame, pd.DataFrame, list]:
    """Assemble one investment year's Network.

    extra_fixed_* are optional already-built vintages (p_nom_extendable=False) carried from
    earlier myopic years. Returned generator/storage frames include candidate-only metadata
    (lifetime_years, fom_cost) so the caller can harvest vintages; those columns are not
    passed to n.add.

    internal_limits: True = internal Links at raw_sum_mw; False = UNCONSTRAINED_LINK_MW
    (20,000) stand-in. neighbors: True = six external buses, external Links at raw_sum_mw,
    and energy-only Market_* generators at Candidate_Gas:CC MC; False = Colorado island.
    Omitting either flag keeps the core (both True). Construction callers in
    _dev_milestones/ pass the pair that milestone used.

    relax_pmin: set p_min_pu=0 on in-state Generators after assembly (expansion cycling).
    Market_* stay at -1. Default True (core).

    aggregate_large_cc: collapse each WasteHeat-linked large CC into one Gas:CC generator.
    Default True (core).

    hybrid_candidates: emit paired Solar+Storage Generator+StorageUnit per zone. Default
    True on build_network (core). build_candidate_components still defaults False.
    """
    # Numbered scripts aren't valid Python identifiers -- importlib doesn't have that restriction.
    timeseries_assembly = importlib.import_module("01_timeseries_assembly")
    load_shape_reconciliation = importlib.import_module("02_load_shape_reconciliation")
    representative_periods = importlib.import_module("03_representative_periods")
    resource_assembly = importlib.import_module("04_resource_assembly")
    build_cf_timeseries = timeseries_assembly.build_cf_timeseries
    reconcile_load_shape = load_shape_reconciliation.reconcile_load_shape
    select_representative_periods = representative_periods.select_representative_periods
    build_existing_fleet_components = resource_assembly.build_existing_fleet_components
    build_candidate_components = resource_assembly.build_candidate_components

    n = pypsa.Network()

    limits = pd.read_csv(TRANSFER_LIMITS_PATH)
    internal = limits[limits["boundary_type"] == "internal"].copy()
    if internal.empty:
        raise ValueError(f"No internal rows in {TRANSFER_LIMITS_PATH}")
    external = _external_rows(limits) if neighbors else None

    print("\n[1/6] Buses...")
    zones = pd.read_csv(ZONE_BA_MAP_PATH)["zone"].tolist()
    n.add("Bus", zones)
    print(f"  {len(zones)} CO buses: {zones}")
    if neighbors:
        n.add("Bus", list(EXPECTED_EXTERNAL_BUSES))
        print(f"  {len(EXPECTED_EXTERNAL_BUSES)} external buses: {list(EXPECTED_EXTERNAL_BUSES)}")

    print("\n[2/6] Links...")
    if internal_limits:
        internal_p_nom = _raw_p_nom(internal, "internal")
        internal_label = "internal_limits (raw_sum_mw)"
    else:
        internal_p_nom = pd.Series(UNCONSTRAINED_LINK_MW, index=internal.index, dtype=float)
        internal_label = f"unconstrained ({UNCONSTRAINED_LINK_MW:,.0f} MW stand-in)"
    _add_zone_links(n, internal, internal_p_nom, internal_label)
    if neighbors:
        external_p_nom = _raw_p_nom(external, "external")
        _add_zone_links(n, external, external_p_nom, "external (raw_sum_mw)")

    print("\n[3/6] Representative weeks (Milestone 2 load + Milestone 3 clustering)...")
    # Do not use weightings_from_timedelta: concatenated weeks are not contiguous in calendar
    # time, so timedelta-based weights would treat month-long gaps as huge storage time-steps.
    load = reconcile_load_shape(target_year)
    cf = build_cf_timeseries()
    representative_snapshots, snapshot_weightings, periods = select_representative_periods(
        target_year, return_periods=True
    )
    n.set_snapshots(representative_snapshots)
    # objective/generators: cluster weights so opex and energy scale to a full year (~8760h).
    # stores: leave at 1.0 -- each snapshot is a real 1-hour step *inside* its week. Putting
    # cluster weights on stores would make a 4-hour battery see each hour as several hours of
    # SOC change.
    n.snapshot_weightings["objective"] = snapshot_weightings.reindex(n.snapshots)
    n.snapshot_weightings["generators"] = snapshot_weightings.reindex(n.snapshots)
    n.add("Load", zones, bus=zones, p_set=load.loc[n.snapshots, zones])
    print(f"  {len(n.snapshots)} snapshots in {len(periods)} periods "
          f"(weighted hours={n.snapshot_weightings['objective'].sum():.1f})")
    for week, weight in periods:
        print(f"    {week[0].strftime('%Y-%m-%d %H:%M')} to "
              f"{week[-1].strftime('%Y-%m-%d %H:%M')}  ({len(week)}h)  weight={weight:.2f}")

    print("\n[4/6] Existing fleet + candidates...")
    ex_gen, ex_sto = build_existing_fleet_components(
        target_year, aggregate_large_cc=aggregate_large_cc,
    )
    cand_gen, cand_sto = build_candidate_components(
        target_year, hybrid_candidates=hybrid_candidates,
    )
    extra_gen = (
        extra_fixed_generators
        if extra_fixed_generators is not None and len(extra_fixed_generators)
        else pd.DataFrame()
    )
    extra_sto = (
        extra_fixed_storage
        if extra_fixed_storage is not None and len(extra_fixed_storage)
        else pd.DataFrame()
    )

    gen_parts = [ex_gen]
    if len(extra_gen):
        gen_parts.append(extra_gen)
    gen_parts.append(cand_gen)
    sto_parts = [ex_sto]
    if len(extra_sto):
        sto_parts.append(extra_sto)
    sto_parts.append(cand_sto)
    generators = pd.concat(gen_parts)
    storage = pd.concat(sto_parts)
    n.add("Generator", generators.index, **_pypsa_attrs(generators, PYPSA_GENERATOR_ATTRS))
    n.add("StorageUnit", storage.index, **_pypsa_attrs(storage, PYPSA_STORAGE_ATTRS))
    print(f"  {len(ex_gen)} existing + {len(extra_gen)} vintage + {len(cand_gen)} candidate generators")
    print(f"  {len(ex_sto)} existing + {len(extra_sto)} vintage + {len(cand_sto)} candidate storage")
    if hybrid_candidates:
        n_hy_g = int((cand_gen["carrier"] == HYBRID_CARRIER).sum())
        n_hy_s = int((cand_sto["carrier"] == HYBRID_CARRIER).sum())
        print(f"  hybrid_candidates: {n_hy_g} Solar+Storage generators, {n_hy_s} storage")
    if neighbors:
        _add_external_market_generators(n, external, cand_gen)
    if relax_pmin:
        _relax_instate_generator_pmin(n, generators, log=True)

    print("\n[5/6] Capacity factors (aligned to representative snapshots)...")
    n_assigned = 0
    for name, row in generators.iterrows():
        col = resolve_cf_column(name, row["carrier"], row["bus"])
        if col is not None:
            n.generators_t.p_max_pu[name] = cf.loc[n.snapshots, col].to_numpy()
            n_assigned += 1
    print(f"  p_max_pu assigned to {n_assigned} of {len(generators)} generators (solar/wind only)")

    # Register names already on buses/generators/links/storage so the consistency
    # check does not dump "undefined carriers" warnings. Stubs only
    # (co2_emissions=0); the 8b cap still uses extra_functionality, not
    # Carrier.co2_emissions. Also assigns plot colors; add_missing_buses is a
    # no-op here because we already create every bus.
    n.sanitize()

    print("\n[6/6] Network assembled.")
    return n, generators, storage, periods


# --- Myopic vintages ---

def _empty_vintage_generators() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "bus", "carrier", "p_nom", "p_nom_extendable", "marginal_cost", "capital_cost",
            "p_min_pu", "lifetime_years", "build_year",
        ]
    ).rename_axis("name")


def _empty_vintage_storage() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "bus", "carrier", "p_nom", "p_nom_extendable", "marginal_cost", "capital_cost",
            "max_hours", "efficiency_store", "efficiency_dispatch", "lifetime_years", "build_year",
        ]
    ).rename_axis("name")


def surviving_vintages(vintages: pd.DataFrame, year: int) -> pd.DataFrame:
    """Keep rows still active at Jan 1 of year: year < build_year + lifetime.

    Same inequality as the existing-fleet filter (RetirementDate > Jan 1 of year).
    A 2030 battery with lifetime_years=15 is active in 2030/2035/2040 and gone in 2045.
    """
    if vintages.empty:
        return vintages
    return vintages[year < vintages["build_year"] + vintages["lifetime_years"]].copy()


def harvest_vintages(
    n,
    generators: pd.DataFrame,
    storage: pd.DataFrame,
    year: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Freeze this year's new builds as fixed vintages (FOM-only capital_cost).

    Hybrid pairs are harvested together: if the solar Generator exceeds
    P_NOM_OPT_MIN, the battery is kept at 0.6 * solar MW even if the battery
    p_nom_opt is under the threshold.
    """
    gen_rows = []
    sto_rows = []
    harvested_hybrid_batteries: set[str] = set()
    built_g = n.generators[
        (n.generators["p_nom_extendable"]) & (n.generators["p_nom_opt"] > P_NOM_OPT_MIN)
    ]
    for name, row in built_g.iterrows():
        meta = generators.loc[name]
        vintage_name = name.replace("Candidate_", "Built_", 1) + f"_{year}"
        solar_mw = float(row["p_nom_opt"])
        gen_rows.append({
            "name": vintage_name,
            "bus": row["bus"],
            "carrier": row["carrier"],
            "p_nom": solar_mw,
            "p_nom_extendable": False,
            "marginal_cost": float(row["marginal_cost"]),
            "capital_cost": float(meta["fom_cost"]),
            "p_min_pu": float(row["p_min_pu"]),
            "lifetime_years": float(meta["lifetime_years"]),
            "build_year": year,
        })
        if row["carrier"] != HYBRID_CARRIER:
            continue
        batt_name = hybrid_battery_name_for_solar(name)
        if batt_name not in n.storage_units.index:
            raise ValueError(f"harvested hybrid solar {name} has no battery {batt_name}")
        if batt_name not in storage.index:
            raise ValueError(f"hybrid battery {batt_name} missing from storage metadata")
        batt_row = n.storage_units.loc[batt_name]
        batt_meta = storage.loc[batt_name]
        batt_mw = HYBRID_BATTERY_MW_PER_SOLAR_MW * solar_mw
        vintage_batt = batt_name.replace("Candidate_", "Built_", 1) + f"_{year}"
        sto_rows.append({
            "name": vintage_batt,
            "bus": batt_row["bus"],
            "carrier": batt_row["carrier"],
            "p_nom": batt_mw,
            "p_nom_extendable": False,
            "marginal_cost": float(batt_row["marginal_cost"]),
            "capital_cost": float(batt_meta["fom_cost"]),
            "max_hours": float(batt_row["max_hours"]),
            "efficiency_store": float(batt_row["efficiency_store"]),
            "efficiency_dispatch": float(batt_row["efficiency_dispatch"]),
            "lifetime_years": float(batt_meta["lifetime_years"]),
            "build_year": year,
        })
        harvested_hybrid_batteries.add(batt_name)

    built_s = n.storage_units[
        (n.storage_units["p_nom_extendable"]) & (n.storage_units["p_nom_opt"] > P_NOM_OPT_MIN)
    ]
    for name, row in built_s.iterrows():
        if name in harvested_hybrid_batteries:
            continue
        if row["carrier"] == HYBRID_CARRIER:
            raise ValueError(
                f"hybrid battery {name} built without a paired solar harvest "
                f"(p_nom_opt={float(row['p_nom_opt']):.4f})"
            )
        meta = storage.loc[name]
        vintage_name = name.replace("Candidate_", "Built_", 1) + f"_{year}"
        sto_rows.append({
            "name": vintage_name,
            "bus": row["bus"],
            "carrier": row["carrier"],
            "p_nom": float(row["p_nom_opt"]),
            "p_nom_extendable": False,
            "marginal_cost": float(row["marginal_cost"]),
            "capital_cost": float(meta["fom_cost"]),
            "max_hours": float(row["max_hours"]),
            "efficiency_store": float(row["efficiency_store"]),
            "efficiency_dispatch": float(row["efficiency_dispatch"]),
            "lifetime_years": float(meta["lifetime_years"]),
            "build_year": year,
        })

    new_gen = (
        pd.DataFrame(gen_rows).set_index("name") if gen_rows else _empty_vintage_generators()
    )
    new_sto = (
        pd.DataFrame(sto_rows).set_index("name") if sto_rows else _empty_vintage_storage()
    )
    return new_gen, new_sto


def _lifetime_years_by_carrier() -> dict[str, float]:
    params = pd.read_csv(CANDIDATE_PARAMS_PATH)
    return {str(row["tech_class"]): float(row["lifetime_years"]) for _, row in params.iterrows()}


def _build_year_from_vintage_name(name: str) -> int:
    suffix = str(name).rsplit("_", 1)[-1]
    try:
        return int(suffix)
    except ValueError as exc:
        raise ValueError(f"Cannot parse build_year from vintage name {name!r}") from exc


def carried_vintages_from_network(n) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rebuild vintage frames from Built_* already stored on a solved checkpoint."""
    lifetimes = _lifetime_years_by_carrier()
    gen_rows = []
    for name, row in n.generators.iterrows():
        if not str(name).startswith("Built_"):
            continue
        carrier = str(row["carrier"])
        if carrier not in lifetimes:
            raise ValueError(f"{name}: no lifetime_years for carrier {carrier}")
        gen_rows.append({
            "name": name,
            "bus": row["bus"],
            "carrier": carrier,
            "p_nom": float(row["p_nom"]),
            "p_nom_extendable": False,
            "marginal_cost": float(row["marginal_cost"]),
            "capital_cost": float(row["capital_cost"]),
            "p_min_pu": float(row["p_min_pu"]),
            "lifetime_years": lifetimes[carrier],
            "build_year": _build_year_from_vintage_name(name),
        })
    sto_rows = []
    for name, row in n.storage_units.iterrows():
        if not str(name).startswith("Built_"):
            continue
        carrier = str(row["carrier"])
        if carrier not in lifetimes:
            raise ValueError(f"{name}: no lifetime_years for carrier {carrier}")
        sto_rows.append({
            "name": name,
            "bus": row["bus"],
            "carrier": carrier,
            "p_nom": float(row["p_nom"]),
            "p_nom_extendable": False,
            "marginal_cost": float(row["marginal_cost"]),
            "capital_cost": float(row["capital_cost"]),
            "max_hours": float(row["max_hours"]),
            "efficiency_store": float(row["efficiency_store"]),
            "efficiency_dispatch": float(row["efficiency_dispatch"]),
            "lifetime_years": lifetimes[carrier],
            "build_year": _build_year_from_vintage_name(name),
        })
    new_gen = (
        pd.DataFrame(gen_rows).set_index("name") if gen_rows else _empty_vintage_generators()
    )
    new_sto = (
        pd.DataFrame(sto_rows).set_index("name") if sto_rows else _empty_vintage_storage()
    )
    return new_gen, new_sto


# --- Reporting ---

def _layer(name: str) -> str:
    if name.startswith("Candidate_"):
        return "new_build"
    if name.startswith("Built_"):
        return "vintage"
    return "existing"


def capacity_records(n, year: int) -> list[dict]:
    records = []
    for table, component in ((n.generators, "Generator"), (n.storage_units, "StorageUnit")):
        for name, row in table.iterrows():
            layer = _layer(name)
            if layer == "new_build":
                p_nom = float(row["p_nom_opt"]) if row["p_nom_opt"] > P_NOM_OPT_MIN else 0.0
            else:
                p_nom = float(row["p_nom"])
            if layer == "new_build" and p_nom <= 0.0:
                continue
            if row["carrier"] == IMPORT_CARRIER:
                continue
            records.append({
                "year": year,
                "layer": layer,
                "component": component,
                "name": name,
                "bus": row["bus"],
                "carrier": row["carrier"],
                "p_nom": p_nom,
            })
    return records


def print_buildout_table(n) -> pd.DataFrame:
    """Short carrier totals: new this year / surviving vintages / existing.

    Prints the table and returns it (index=carrier, columns existing/vintage/new_build/total).
    """
    frames = []
    for table, p_col in ((n.generators, "p_nom"), (n.storage_units, "p_nom")):
        part = table[["carrier", p_col]].copy()
        part["layer"] = [_layer(name) for name in table.index]
        part["mw"] = table[p_col]
        built_opt = table["p_nom_extendable"] & (table["p_nom_opt"] > P_NOM_OPT_MIN)
        part.loc[built_opt, "mw"] = table.loc[built_opt, "p_nom_opt"]
        part.loc[part["layer"].eq("new_build") & ~built_opt, "mw"] = 0.0
        frames.append(part[["carrier", "layer", "mw"]])
    stacked = pd.concat(frames)
    stacked = stacked[stacked["carrier"] != IMPORT_CARRIER]
    pivot = (
        stacked.groupby(["carrier", "layer"])["mw"].sum()
        .unstack(fill_value=0.0)
        .reindex(columns=["existing", "vintage", "new_build"], fill_value=0.0)
    )
    pivot["total"] = pivot.sum(axis=1)
    pivot = pivot[pivot["total"] > P_NOM_OPT_MIN].sort_values("total", ascending=False)
    print(pivot.to_string(float_format=lambda x: f"{x:,.1f}"))
    return pivot


def generation_by_carrier(n) -> pd.DataFrame:
    """Snapshot-weighted GWh by carrier: generators from p, storage from p_dispatch.

    Import Market_* land in their own `import` carrier row when present.
    """
    w = n.snapshot_weightings["generators"].reindex(n.snapshots).astype(float)
    rows: list[dict] = []
    if "p" in n.generators_t and not n.generators.empty:
        p = n.generators_t.p
        for name in p.columns:
            if name not in n.generators.index:
                continue
            gwh = float((p[name] * w).sum()) / 1e3
            rows.append({
                "carrier": n.generators.at[name, "carrier"],
                "component": "Generator",
                "gwh": gwh,
            })
    if not n.storage_units.empty and "p_dispatch" in n.storage_units_t:
        p_d = n.storage_units_t.p_dispatch
        for name in p_d.columns:
            if name not in n.storage_units.index:
                continue
            gwh = float((p_d[name] * w).sum()) / 1e3
            rows.append({
                "carrier": n.storage_units.at[name, "carrier"],
                "component": "StorageUnit",
                "gwh": gwh,
            })
    if not rows:
        return pd.DataFrame(columns=["carrier", "component", "gwh"])
    return (
        pd.DataFrame(rows)
        .groupby(["carrier", "component"], as_index=False)["gwh"].sum()
        .sort_values(["component", "gwh"], ascending=[True, False])
        .reset_index(drop=True)
    )


def storage_charge_by_carrier(n) -> pd.DataFrame:
    """Snapshot-weighted GWh by carrier: storage charging draw (p_store).

    Companion to generation_by_carrier(), which reports StorageUnit output as
    p_dispatch (discharge to the grid) only. That is the right number for
    "how much energy did this technology deliver," but it is not the whole
    picture: the energy that charged a battery or pumped-hydro reservoir was
    already counted once, when whatever generator produced it ran. Charging
    is not "negative generation" served to load -- it is energy pulled back
    out of the system, and because round-trip efficiency is under 100% it is
    always larger than the matching discharge. A generation-by-technology
    chart that stacks discharge as a supply category without also showing
    (or subtracting) this draw double-counts that energy and overstates
    supply by roughly the charging total.

    Written to its own file (storage_charge_by_year.csv) rather than appended
    to generation_by_year.csv, so existing consumers of that file's schema
    (e.g. dispatch_matches_generation) are unaffected.
    """
    w = n.snapshot_weightings["generators"].reindex(n.snapshots).astype(float)
    rows: list[dict] = []
    if not n.storage_units.empty and "p_store" in n.storage_units_t:
        p_s = n.storage_units_t.p_store
        for name in p_s.columns:
            if name not in n.storage_units.index:
                continue
            gwh = float((p_s[name] * w).sum()) / 1e3
            rows.append({
                "carrier": n.storage_units.at[name, "carrier"],
                "component": "StorageUnit",
                "gwh": gwh,
            })
    if not rows:
        return pd.DataFrame(columns=["carrier", "component", "gwh"])
    return (
        pd.DataFrame(rows)
        .groupby(["carrier", "component"], as_index=False)["gwh"].sum()
        .sort_values(["component", "gwh"], ascending=[True, False])
        .reset_index(drop=True)
    )


def lmp_by_bus(n) -> pd.DataFrame:
    """Mean snapshot LMP ($/MWh) by bus."""
    mean = n.buses_t.marginal_price.mean()
    return mean.rename("mean_lmp").rename_axis("bus").reset_index()


def print_soc_check(n, periods) -> None:
    if n.storage_units.empty:
        print("  (no storage)")
        return
    p_store = n.storage_units_t.p_store
    p_dispatch = n.storage_units_t.p_dispatch
    eff_s = n.storage_units["efficiency_store"]
    eff_d = n.storage_units["efficiency_dispatch"]
    for i, (week, _) in enumerate(periods):
        net = (p_store.loc[week] * eff_s - p_dispatch.loc[week] / eff_d).sum(axis=0)
        worst = net.abs().idxmax()
        print(f"  week {i}: max |net| = {net.abs().max():.4f} MWh  ({worst})")


def print_net_interchange(n) -> pd.DataFrame:
    """Objective-weighted net flow on external Links. Positive = CO export (TWh)."""
    empty = pd.DataFrame(columns=["interface", "co_bus", "far_bus", "twh"])
    if n.links.empty or "p0" not in n.links_t:
        return empty
    co_zones = set(pd.read_csv(ZONE_BA_MAP_PATH)["zone"])
    ext_names = [
        name
        for name, row in n.links.iterrows()
        if (row["bus0"] in co_zones) != (row["bus1"] in co_zones)
    ]
    if not ext_names:
        return empty
    weights = n.snapshot_weightings["objective"]
    p0 = n.links_t.p0
    print("Net interchange by interface (TWh, + = CO export):", flush=True)
    total_twh = 0.0
    rows: list[dict] = []
    for name in ext_names:
        bus0 = n.links.at[name, "bus0"]
        bus1 = n.links.at[name, "bus1"]
        mwh = float((p0[name] * weights).sum())
        export_mwh = mwh if bus0 in co_zones else -mwh
        twh = export_mwh / 1e6
        total_twh += twh
        co_bus, far_bus = (bus0, bus1) if bus0 in co_zones else (bus1, bus0)
        print(f"  {name}: {co_bus} <-> {far_bus}  {twh:+.3f} TWh", flush=True)
        rows.append({
            "interface": name,
            "co_bus": co_bus,
            "far_bus": far_bus,
            "twh": twh,
        })
    print(f"  total  {total_twh:+.3f} TWh", flush=True)
    rows.append({
        "interface": "total",
        "co_bus": "",
        "far_bus": "",
        "twh": total_twh,
    })
    return pd.DataFrame(rows)


def gross_interchange_by_market(n) -> pd.DataFrame:
    """Snapshot-weighted gross import and export GWh, per Market_* generator.

    Companion to print_net_interchange() (Link-based, net position only,
    positive = CO export) and print_co2_table()'s import_mwh (all markets
    combined, and only computable during a live solve because it checks the
    CO2_IMPORT_FLOW model variable). This reports both directions separately,
    per neighbor market, reading only n.generators_t.p -- so, like
    storage_charge_by_carrier, it is safe to recompute from a saved
    checkpoint with no live solve and no dependency on n.model.

    Clip PER GENERATOR before summing across snapshots, not the other way
    round: Colorado can import on one tie while exporting on another in the
    same hour, and summing generators together before clipping would net
    that activity away (this is exactly the bug caught and fixed while
    prototyping the manuscript figure that motivated this function).

    Reports two independent, unsigned magnitudes rather than a single signed
    net figure on purpose, so different consumers can apply whatever sign
    convention they need: a net-interchange diagnostic can take
    gross_export - gross_import (matching print_net_interchange's "positive =
    CO export"), while a source/sink energy-balance chart can add import and
    subtract export, or vice versa -- neither has to adopt the other's
    convention, and this file does not pick one.
    """
    w = n.snapshot_weightings["generators"].reindex(n.snapshots).astype(float)
    markets = _market_generator_names(n)
    rows: list[dict] = []
    for name in markets:
        p = n.generators_t.p[name]
        gross_import = float((p.clip(lower=0) * w).sum()) / 1e3  # MWh -> GWh
        gross_export = float((-p.clip(upper=0) * w).sum()) / 1e3
        rows.append({
            "market": name,
            "gross_import_gwh": gross_import,
            "gross_export_gwh": gross_export,
        })
    df = pd.DataFrame(rows, columns=["market", "gross_import_gwh", "gross_export_gwh"])
    if not df.empty:
        totals = df[["gross_import_gwh", "gross_export_gwh"]].sum()
        df = pd.concat(
            [df, pd.DataFrame([{"market": "total", **totals.to_dict()}])],
            ignore_index=True,
        )
    return df


# --- Annual cost / NPV and representative-week dispatch ---

_ATB_TABLE = None


def _atb_table() -> pd.DataFrame:
    global _ATB_TABLE
    if _ATB_TABLE is None:
        _ATB_TABLE = pd.read_csv(ATB_LOOKUP_PATH)
    return _ATB_TABLE


def _atb_occ_fom_per_mw(year: int, tech_class: str) -> tuple[float, float]:
    """Overnight and FOM in $/MW and $/MW-yr from atb_candidate_lookup (Moderate)."""
    df = _atb_table()
    row = df[
        (df["tech_class"] == tech_class)
        & (df["atb_year"] == year)
        & (df["scenario"] == ATB_SCENARIO)
    ]
    if len(row) != 1:
        raise ValueError(
            f"ATB lookup expected one row for {tech_class!r} {year} {ATB_SCENARIO}; "
            f"got {len(row)}"
        )
    occ = float(row["occ_per_kw"].iloc[0]) * 1000.0
    fom = float(row["fixed_om_per_kw_yr"].iloc[0]) * 1000.0
    if pd.isna(occ) or pd.isna(fom):
        raise ValueError(f"ATB OCC/FOM missing for {tech_class!r} {year}")
    return occ, fom


def _is_hybrid_battery(name: str, carrier: str) -> bool:
    if carrier != HYBRID_CARRIER:
        return False
    text = str(name)
    return text.endswith(HYBRID_BATTERY_SUFFIX) or (HYBRID_BATTERY_SUFFIX + "_") in text


def _new_mw(row) -> float:
    if not bool(row["p_nom_extendable"]):
        return 0.0
    mw = float(row["p_nom_opt"])
    return mw if mw > P_NOM_OPT_MIN else 0.0


def _snapshot_generator_weights(n) -> pd.Series:
    return n.snapshot_weightings["generators"].reindex(n.snapshots).astype(float)


def _weighted_energy_cost(p: pd.Series, weight: pd.Series, marginal_cost: float) -> float:
    return float((p.reindex(weight.index).astype(float) * weight).sum()) * float(marginal_cost)


def _lp_objective(n) -> float:
    obj = getattr(n, "objective", None)
    if obj is None or (isinstance(obj, float) and pd.isna(obj)):
        return float("nan")
    return float(obj)


def cost_of_year(n, year: int) -> dict:
    """Cash-flow decomposition for one investment year. Does not NPV.

    Overnight OCC and FOM_new come from ATB (fom_cost is stripped before n.add).
    lp_objective is n.objective when present (diagnostic; not the cost).
    """
    w = _snapshot_generator_weights(n)
    capex_overnight = 0.0
    fom_new = 0.0
    fom_existing = 0.0
    fom_vintage = 0.0
    new_annuity = 0.0

    for table in (n.generators, n.storage_units):
        if table.empty:
            continue
        for name, row in table.iterrows():
            layer = _layer(name)
            if row["carrier"] == IMPORT_CARRIER:
                continue
            if layer == "new_build":
                mw = _new_mw(row)
                if mw <= 0.0:
                    continue
                new_annuity += float(row["capital_cost"]) * mw
                if _is_hybrid_battery(name, row["carrier"]):
                    continue
                occ, fom = _atb_occ_fom_per_mw(year, row["carrier"])
                capex_overnight += occ * mw
                fom_new += fom * mw
            elif layer == "vintage":
                fom_vintage += float(row["capital_cost"]) * float(row["p_nom"])
            else:
                fom_existing += float(row["capital_cost"]) * float(row["p_nom"])

    opex_instate = 0.0
    import_cost = 0.0
    export_revenue = 0.0
    if "p" in n.generators_t and not n.generators.empty:
        p_t = n.generators_t.p
        for name, row in n.generators.iterrows():
            if name not in p_t.columns:
                continue
            p = p_t[name]
            mc = float(row["marginal_cost"])
            if row["carrier"] == IMPORT_CARRIER:
                import_cost += _weighted_energy_cost(p.clip(lower=0.0), w, mc)
                export_revenue += _weighted_energy_cost(-p.clip(upper=0.0), w, mc)
            else:
                opex_instate += _weighted_energy_cost(p, w, mc)
    if not n.storage_units.empty and "p_dispatch" in n.storage_units_t:
        p_d = n.storage_units_t.p_dispatch
        for name, row in n.storage_units.iterrows():
            if name not in p_d.columns:
                continue
            opex_instate += _weighted_energy_cost(p_d[name], w, float(row["marginal_cost"]))

    annual = (
        capex_overnight + fom_existing + fom_vintage + fom_new
        + opex_instate + import_cost - export_revenue
    )
    annual_ex_trade = capex_overnight + fom_existing + fom_vintage + fom_new + opex_instate
    lp_objective = _lp_objective(n)
    identity_rhs = new_annuity + opex_instate + import_cost - export_revenue
    identity_gap = (
        float("nan") if pd.isna(lp_objective) else lp_objective - identity_rhs
    )
    return {
        "year": year,
        "capex_overnight": capex_overnight,
        "fom_existing": fom_existing,
        "fom_vintage": fom_vintage,
        "fom_new": fom_new,
        "opex_instate": opex_instate,
        "import_cost": import_cost,
        "export_revenue": export_revenue,
        "annual_system_cost": annual,
        "annual_system_cost_ex_trade": annual_ex_trade,
        "lp_objective": lp_objective,
        "identity_rhs": identity_rhs,
        "identity_gap": identity_gap,
    }


def _cost_csv_row(cost: dict) -> dict:
    return {k: cost[k] for k in COST_CSV_COLS}


def print_cost_table(row: dict) -> None:
    print("Annual cash-flow cost ($):", flush=True)
    for key in (
        "capex_overnight", "fom_existing", "fom_vintage", "fom_new",
        "opex_instate", "import_cost", "export_revenue",
        "annual_system_cost", "annual_system_cost_ex_trade", "lp_objective",
    ):
        print(f"  {key}  ${row[key]:,.0f}", flush=True)
    gap = row["identity_gap"]
    if pd.notna(gap):
        print(f"  identity_gap  ${gap:,.2f}", flush=True)


def npv_from_cost_table(cost: pd.DataFrame) -> dict:
    """NPV of cash flows: overnight once in the build year; FOM/opex/trade held for step_years."""
    if cost.empty or "year" not in cost.columns:
        raise ValueError("cost table has no year column")
    by_year = cost.set_index("year")
    npv_capex = 0.0
    npv_fom = 0.0
    npv_opex = 0.0
    npv_trade = 0.0
    for year, row in by_year.iterrows():
        year = int(year)
        fom = float(row["fom_existing"] + row["fom_vintage"] + row["fom_new"])
        opex = float(row["opex_instate"])
        trade = float(row["import_cost"] - row["export_revenue"])
        capex = float(row["capex_overnight"])
        for k in range(NPV_STEP_YEARS):
            t = year + k
            disc = 1.0 / ((1.0 + NPV_DISCOUNT_RATE) ** (t - NPV_BASE_YEAR))
            if k == 0:
                npv_capex += capex * disc
            npv_fom += fom * disc
            npv_opex += opex * disc
            npv_trade += trade * disc
    npv_total = npv_capex + npv_fom + npv_opex + npv_trade
    npv_ex_trade = npv_capex + npv_fom + npv_opex
    return {
        "discount_rate": NPV_DISCOUNT_RATE,
        "base_year": NPV_BASE_YEAR,
        "step_years": NPV_STEP_YEARS,
        "npv_total": npv_total,
        "npv_capex_overnight": npv_capex,
        "npv_fom": npv_fom,
        "npv_opex_instate": npv_opex,
        "npv_trade_net": npv_trade,
        "npv_ex_trade": npv_ex_trade,
    }


def _week_id_series(n, periods) -> pd.Series:
    week_id = pd.Series(pd.NA, index=n.snapshots, dtype="Int64")
    for i, (week, _) in enumerate(periods):
        hits = week_id.index.isin(week)
        week_id.loc[hits] = i
    missing = week_id.isna()
    if missing.any():
        raise ValueError(
            f"{int(missing.sum())} snapshots have no week_id; do not stride the "
            f"flattened index at 168 hours"
        )
    return week_id


def _stack_component(values: pd.DataFrame, snapshots, name_col="name") -> pd.DataFrame:
    aligned = values.reindex(index=snapshots)
    aligned.index.name = "snapshot"
    return aligned.reset_index().melt(
        id_vars="snapshot", var_name=name_col, value_name="value",
    )


def dispatch_table(n, periods) -> pd.DataFrame:
    """Long-format modeled hours (representative weeks only)."""
    snapshots = n.snapshots
    week_id = _week_id_series(n, periods)
    weight = _snapshot_generator_weights(n)
    frames: list[pd.DataFrame] = []

    if "p" in n.generators_t and not n.generators.empty:
        g = _stack_component(n.generators_t.p, snapshots)
        g["component"] = "Generator"
        g["bus"] = g["name"].map(n.generators["bus"])
        g["carrier"] = g["name"].map(n.generators["carrier"])
        g["p_mw"] = g["value"]
        frames.append(g)

    if not n.storage_units.empty:
        p_d = (
            n.storage_units_t.p_dispatch.reindex(index=snapshots)
            if "p_dispatch" in n.storage_units_t else pd.DataFrame(index=snapshots)
        )
        p_s = (
            n.storage_units_t.p_store.reindex(index=snapshots)
            if "p_store" in n.storage_units_t else pd.DataFrame(index=snapshots)
        )
        soc = (
            n.storage_units_t.state_of_charge.reindex(index=snapshots)
            if "state_of_charge" in n.storage_units_t else pd.DataFrame(index=snapshots)
        )
        names = list(n.storage_units.index)
        p_d = p_d.reindex(columns=names).fillna(0.0)
        p_s = p_s.reindex(columns=names).fillna(0.0)
        s = _stack_component(p_d - p_s, snapshots)
        s["component"] = "StorageUnit"
        s["bus"] = s["name"].map(n.storage_units["bus"])
        s["carrier"] = s["name"].map(n.storage_units["carrier"])
        s["p_mw"] = s["value"]
        s["p_store_mw"] = _stack_component(p_s, snapshots)["value"].to_numpy()
        if not soc.empty:
            soc = soc.reindex(columns=names)
            s["soc_mwh"] = _stack_component(soc, snapshots)["value"].to_numpy()
        frames.append(s)

    load_t = None
    if not n.loads.empty:
        if "p_set" in n.loads_t:
            load_t = n.loads_t.p_set
        elif "p" in n.loads_t:
            load_t = n.loads_t.p
    if load_t is not None and not load_t.empty:
        ld = _stack_component(load_t, snapshots)
        ld["component"] = "Load"
        ld["bus"] = ld["name"].map(n.loads["bus"]) if "bus" in n.loads.columns else ld["name"]
        ld["carrier"] = ""
        ld["p_mw"] = ld["value"]
        frames.append(ld)

    if not n.links.empty and "p0" in n.links_t:
        lk = _stack_component(n.links_t.p0, snapshots)
        lk["component"] = "Link"
        lk["bus"] = lk["name"].map(n.links["bus0"])
        lk["carrier"] = ""
        lk["p_mw"] = lk["value"]
        frames.append(lk)

    if not n.buses.empty and "marginal_price" in n.buses_t:
        b = _stack_component(n.buses_t.marginal_price, snapshots)
        b["component"] = "Bus"
        b["bus"] = b["name"]
        b["carrier"] = ""
        b["lmp"] = b["value"]
        frames.append(b)

    if not frames:
        return pd.DataFrame(
            columns=[
                "snapshot", "week_id", "weight", "component", "name", "bus",
                "carrier", "p_mw", "p_store_mw", "soc_mwh", "lmp",
            ]
        )
    out = pd.concat(frames, ignore_index=True)
    out["week_id"] = out["snapshot"].map(week_id)
    out["weight"] = out["snapshot"].map(weight)
    for col in ("p_mw", "p_store_mw", "soc_mwh", "lmp", "carrier"):
        if col not in out.columns:
            out[col] = pd.NA
    return out[
        [
            "snapshot", "week_id", "weight", "component", "name", "bus",
            "carrier", "p_mw", "p_store_mw", "soc_mwh", "lmp",
        ]
    ]


def dispatch_matches_generation(dispatch: pd.DataFrame, generation: pd.DataFrame) -> list[str]:
    """Return mismatch messages. Generator p_mw and StorageUnit discharge vs generation_by_year."""
    failures: list[str] = []
    if dispatch.empty:
        return ["dispatch table is empty"]
    w = dispatch["weight"].astype(float)
    gen = dispatch[dispatch["component"] == "Generator"].copy()
    gen["gwh"] = gen["p_mw"].astype(float) * w.loc[gen.index] / 1e3
    gen_sum = gen.groupby("carrier", dropna=False)["gwh"].sum()
    expected_g = generation[generation["component"] == "Generator"].groupby("carrier")["gwh"].sum()
    for carrier in sorted(set(gen_sum.index) | set(expected_g.index)):
        got = float(gen_sum.get(carrier, 0.0))
        exp = float(expected_g.get(carrier, 0.0))
        if abs(got - exp) > DISPATCH_GWH_TOL:
            failures.append(f"Generator {carrier}: dispatch {got:.6f} GWh vs generation {exp:.6f}")
    sto = dispatch[dispatch["component"] == "StorageUnit"].copy()
    if len(sto):
        discharge = sto["p_mw"].astype(float) + sto["p_store_mw"].fillna(0.0).astype(float)
        sto["gwh"] = discharge * w.loc[sto.index] / 1e3
        sto_sum = sto.groupby("carrier", dropna=False)["gwh"].sum()
        expected_s = (
            generation[generation["component"] == "StorageUnit"].groupby("carrier")["gwh"].sum()
        )
        for carrier in sorted(set(sto_sum.index) | set(expected_s.index)):
            got = float(sto_sum.get(carrier, 0.0))
            exp = float(expected_s.get(carrier, 0.0))
            if abs(got - exp) > DISPATCH_GWH_TOL:
                failures.append(
                    f"StorageUnit {carrier}: dispatch {got:.6f} GWh vs generation {exp:.6f}"
                )
    return failures


def _write_npv_if_complete(cost: pd.DataFrame, out_dir) -> None:
    years = set(int(y) for y in cost["year"]) if len(cost) else set()
    if years != set(INVESTMENT_YEARS):
        return
    row = npv_from_cost_table(cost)
    pd.DataFrame([row]).to_csv(out_dir / "npv.csv", index=False)
    print(
        f"  NPV (r={row['discount_rate']}, base={row['base_year']}, "
        f"step={row['step_years']}): total ${row['npv_total']:,.0f}  "
        f"ex_trade ${row['npv_ex_trade']:,.0f}",
        flush=True,
    )


def _periods_for_year(year: int):
    representative_periods = importlib.import_module("03_representative_periods")
    _, _, periods = representative_periods.select_representative_periods(
        year, return_periods=True,
    )
    return periods


def write_year_cost_dispatch(
    n, year: int, periods, out_dir, *, generation=None,
) -> tuple[dict, list[str]]:
    """Write dispatch_{year}.csv; return (cost_of_year row, dispatch-vs-generation mismatches)."""
    cost = cost_of_year(n, year)
    print_cost_table(cost)
    gap = cost["identity_gap"]
    if pd.notna(gap) and abs(gap) > COST_IDENTITY_TOL:
        print(
            f"  WARNING: cost identity |gap|=${gap:,.2f} exceeds ${COST_IDENTITY_TOL:g}",
            flush=True,
        )
    dispatch = dispatch_table(n, periods)
    dispatch["carrier"] = dispatch["carrier"].fillna("").astype(str)
    path = out_dir / f"dispatch_{year}.csv"
    dispatch.to_csv(path, index=False)
    print(f"  wrote {path.relative_to(PROJECT_ROOT)} ({len(dispatch):,} rows)", flush=True)
    if generation is None:
        generation = generation_by_carrier(n)
    mismatches = dispatch_matches_generation(dispatch, generation)
    if mismatches:
        for msg in mismatches:
            print(f"  WARNING: dispatch vs generation: {msg}", flush=True)
    return cost, mismatches


def write_cost_dispatch_from_checkpoints(network_prefix: str) -> None:
    """Rebuild cost/NPV/dispatch CSVs from {year}.nc. No solve."""
    out_dir = run_output_dir(network_prefix)
    pypsa_lib = _import_installed_pypsa()
    cost_rows: list[dict] = []
    gen_csv = out_dir / "generation_by_year.csv"
    generation_all = pd.read_csv(gen_csv) if gen_csv.exists() else None
    summary_csv = out_dir / "summary_by_year.csv"
    summary = pd.read_csv(summary_csv) if summary_csv.exists() else None
    failures: list[str] = []
    for year in INVESTMENT_YEARS:
        path = run_checkpoint_path(network_prefix, year)
        if not path.exists():
            raise FileNotFoundError(f"Cannot backfill: missing {path}")
        print(f"\n=== backfill {network_prefix} {year} ===", flush=True)
        n = pypsa_lib.Network(str(path))
        if pd.isna(_lp_objective(n)) and summary is not None:
            hit = summary.loc[summary["year"] == year, "objective"]
            if len(hit) == 1:
                n.objective = float(hit.iloc[0])
        periods = _periods_for_year(year)
        generation = None
        if generation_all is not None:
            generation = generation_all[generation_all["year"] == year].drop(
                columns=["year"], errors="ignore",
            )
        cost, mismatches = write_year_cost_dispatch(
            n, year, periods, out_dir, generation=generation,
        )
        cost_rows.append(cost)
        gap = cost["identity_gap"]
        if pd.isna(gap) or abs(gap) > COST_IDENTITY_TOL:
            failures.append(f"{year}: identity_gap={gap}")
        failures.extend(f"{year}: {m}" for m in mismatches)
    cost_df = pd.DataFrame([_cost_csv_row(r) for r in cost_rows])
    cost_df.to_csv(out_dir / "cost_by_year.csv", index=False)
    _write_npv_if_complete(cost_df, out_dir)
    if failures:
        raise SystemExit("cost/dispatch backfill gates failed:\n  " + "\n  ".join(failures))
    print("\n=== cost/dispatch backfill OK ===", flush=True)


def write_storage_charge_from_checkpoints(network_prefix: str) -> None:
    """Write storage_charge_by_year.csv from {year}.nc. No solve.

    Backfill for scenarios solved before storage_charge_by_carrier() existed.
    p_store is already sitting in each saved checkpoint; this just reads it
    back out and reports it, the same no-solve pattern as
    write_cost_dispatch_from_checkpoints.
    """
    out_dir = run_output_dir(network_prefix)
    pypsa_lib = _import_installed_pypsa()
    charge_parts: list[pd.DataFrame] = []
    for year in INVESTMENT_YEARS:
        path = run_checkpoint_path(network_prefix, year)
        if not path.exists():
            raise FileNotFoundError(f"Cannot backfill: missing {path}")
        n = pypsa_lib.Network(str(path))
        charge = storage_charge_by_carrier(n)
        charge.insert(0, "year", year)
        charge_parts.append(charge)
        print(f"  {network_prefix} {year}: {len(charge)} storage carrier rows", flush=True)
    _concat_write(charge_parts, out_dir / "storage_charge_by_year.csv")
    print(f"=== {network_prefix} storage charge backfill OK ===", flush=True)


def write_gross_interchange_from_checkpoints(network_prefix: str) -> None:
    """Write gross_interchange_by_year.csv from {year}.nc. No solve.

    Same no-solve backfill pattern as write_storage_charge_from_checkpoints;
    see gross_interchange_by_market for why this is safe to recompute from a
    saved checkpoint (unlike print_co2_table's import_mwh).
    """
    out_dir = run_output_dir(network_prefix)
    pypsa_lib = _import_installed_pypsa()
    parts: list[pd.DataFrame] = []
    for year in INVESTMENT_YEARS:
        path = run_checkpoint_path(network_prefix, year)
        if not path.exists():
            raise FileNotFoundError(f"Cannot backfill: missing {path}")
        n = pypsa_lib.Network(str(path))
        interchange = gross_interchange_by_market(n)
        interchange.insert(0, "year", year)
        parts.append(interchange)
        print(f"  {network_prefix} {year}: {len(interchange)} market rows", flush=True)
    _concat_write(parts, out_dir / "gross_interchange_by_year.csv")
    print(f"=== {network_prefix} gross interchange backfill OK ===", flush=True)


def run_output_dir(group: str):
    """One subfolder per solve family: pypsa/scenarios/{group}/."""
    path = PROJECT_ROOT / "pypsa" / "scenarios" / group
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_checkpoint_path(group: str, year: int):
    """One subfolder per solve family: pypsa/scenarios/{group}/{year}.nc."""
    return run_output_dir(group) / f"{year}.nc"


def run_capacity_csv_path(group: str):
    """Capacity summary next to checkpoints: pypsa/scenarios/{group}/capacity_by_year.csv."""
    return run_output_dir(group) / "capacity_by_year.csv"


def run_solve_log_path(group: str):
    """Full terminal capture next to checkpoints: pypsa/scenarios/{group}/solve.log."""
    return run_output_dir(group) / "solve.log"


def _stream_fileno(stream) -> int | None:
    try:
        return stream.fileno()
    except (AttributeError, io.UnsupportedOperation, OSError):
        return None


def _scrub_project_root(text: str) -> str:
    """Drop the local absolute path prefix so solve.log stays portable/anonymous."""
    return text.replace(str(PROJECT_ROOT), ".")


class _StreamTee(io.TextIOBase):
    """Python-level stdout/stderr copy when fileno is unavailable."""

    def __init__(self, inner, log_file, lock: threading.Lock):
        self._inner = inner
        self._log = log_file
        self._lock = lock

    def write(self, s):
        if not isinstance(s, str):
            s = s.decode("utf-8", "replace")
        self._inner.write(s)
        with self._lock:
            self._log.write(_scrub_project_root(s))
        return len(s)

    def flush(self):
        self._inner.flush()
        with self._lock:
            self._log.flush()

    def fileno(self):
        return self._inner.fileno()

    def isatty(self):
        return self._inner.isatty()


def _start_fd_tee(
    src_fd: int,
    log_file,
    lock: threading.Lock,
    encoding: str,
) -> tuple[int, threading.Thread, int, io.TextIOBase]:
    """Point src_fd at a pipe; copy chunks to the original fd and the log file."""
    saved_fd = os.dup(src_fd)
    restored = os.fdopen(
        saved_fd, "w", encoding=encoding, errors="replace", buffering=1, closefd=False
    )
    pipe_r, pipe_w = os.pipe()
    os.dup2(pipe_w, src_fd)
    os.close(pipe_w)

    def reader() -> None:
        while True:
            try:
                chunk = os.read(pipe_r, 4096)
            except OSError:
                break
            if not chunk:
                break
            text = chunk.decode(encoding, "replace")
            restored.write(text)
            restored.flush()
            with lock:
                log_file.write(_scrub_project_root(text))
                log_file.flush()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return pipe_r, thread, saved_fd, restored


@contextlib.contextmanager
def tee_solve_log(network_prefix: str, *, append: bool = False):
    """Copy process stdout+stderr (including HiGHS fd writes) to scenarios/{prefix}/solve.log.

    Fresh sequences overwrite; pass append=True for resume_after_year. The HiGHS year
    banner still intercepts fd 1 during n.optimize; its restored stream is this tee,
    so iteration lines are in the log too.
    """
    log_path = run_solve_log_path(network_prefix)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    log_file = open(log_path, "a" if append else "w", encoding="utf-8", errors="replace", buffering=1)
    stamp = datetime.now().isoformat(timespec="seconds")
    kind = "append" if append else "start"
    log_file.write(f"--- solve.log {network_prefix} {kind} {stamp} ---\n")
    log_file.flush()

    stdout_fd = _stream_fileno(sys.stdout)
    stderr_fd = _stream_fileno(sys.stderr)
    lock = threading.Lock()
    old_out, old_err = sys.stdout, sys.stderr
    tees: list[tuple] = []
    try:
        if stdout_fd is None or stderr_fd is None:
            sys.stdout = _StreamTee(old_out, log_file, lock)
            sys.stderr = _StreamTee(old_err, log_file, lock)
            print(f"  solve log: {log_path.relative_to(PROJECT_ROOT)}", flush=True)
            yield log_path
        else:
            tees.append(_start_fd_tee(stdout_fd, log_file, lock, encoding) + (stdout_fd,))
            if stderr_fd != stdout_fd:
                tees.append(_start_fd_tee(stderr_fd, log_file, lock, encoding) + (stderr_fd,))
            print(f"  solve log: {log_path.relative_to(PROJECT_ROOT)}", flush=True)
            yield log_path
    finally:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        sys.stdout = old_out
        sys.stderr = old_err
        for pipe_r, thread, saved_fd, restored, src_fd in tees:
            try:
                os.dup2(saved_fd, src_fd)
            except OSError:
                pass
            thread.join(timeout=5)
            restored.close()
            for fd in (saved_fd, pipe_r):
                try:
                    os.close(fd)
                except OSError:
                    pass
        log_file.close()


# --- HiGHS ---

_HIGHS_ITER_HEADER = re.compile(r"^\s*Iteration\s+Objective")
_HIGHS_ITER_ROW = re.compile(r"^\s*\d+")


class _SimplexYearFilter:
    """Insert a year banner above HiGHS's Iteration table; tag each table row with the year."""

    def __init__(self, year: int, step: int | None = None, n_years: int | None = None):
        if step is not None and n_years is not None:
            label = f"YEAR {year} (step {step}/{n_years})"
        else:
            label = f"YEAR {year}"
        self.prefix = f"{year} | "
        self.banner = f"\n========== HiGHS simplex: {label} ==========\n"
        self._buf = ""
        self._in_table = False
        self._injected = False

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            out.append(self._transform(line) + "\n")
        return "".join(out)

    def flush_rest(self) -> str:
        if not self._buf:
            return ""
        text = self._transform(self._buf)
        self._buf = ""
        return text

    def _transform(self, line: str) -> str:
        raw = line.rstrip("\r")
        if not self._injected and _HIGHS_ITER_HEADER.search(raw):
            self._injected = True
            self._in_table = True
            return self.banner + self.prefix + line
        if self._in_table:
            if _HIGHS_ITER_HEADER.search(raw) or _HIGHS_ITER_ROW.match(raw):
                return self.prefix + line
            self._in_table = False
        return line


class _TextIOFilter(io.TextIOBase):
    def __init__(self, inner, filt: _SimplexYearFilter):
        self._inner = inner
        self._filt = filt

    def write(self, s):
        if not isinstance(s, str):
            s = s.decode("utf-8", "replace")
        out = self._filt.feed(s)
        if out:
            self._inner.write(out)
        return len(s)

    def flush(self):
        rest = self._filt.flush_rest()
        if rest:
            self._inner.write(rest)
        self._inner.flush()

    def fileno(self):
        return self._inner.fileno()

    def isatty(self):
        return self._inner.isatty()


@contextlib.contextmanager
def highs_simplex_year_banner(
    year: int, step: int | None = None, n_years: int | None = None
):
    """Tee C-level stdout during HiGHS so a year heading sits above the iteration table.

    HiGHS writes the Iteration table to the process stdout fd, not sys.stdout, so a
    Python print before n.optimize() scrolls away under presolve. This intercepts fd 1
    for the duration of the solve.
    """
    filt = _SimplexYearFilter(year, step=step, n_years=n_years)
    try:
        stdout_fd = sys.stdout.fileno()
    except (AttributeError, io.UnsupportedOperation):
        stdout_fd = None

    if stdout_fd is None:
        wrapper = _TextIOFilter(sys.stdout, filt)
        old = sys.stdout
        sys.stdout = wrapper
        try:
            yield
        finally:
            wrapper.flush()
            sys.stdout = old
        return

    sys.stdout.flush()
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    saved_fd = os.dup(stdout_fd)
    restored = os.fdopen(
        saved_fd, "w", encoding=encoding, errors="replace", buffering=1, closefd=False
    )
    pipe_r, pipe_w = os.pipe()
    os.dup2(pipe_w, stdout_fd)
    os.close(pipe_w)

    def reader() -> None:
        while True:
            try:
                chunk = os.read(pipe_r, 4096)
            except OSError:
                break
            if not chunk:
                break
            out = filt.feed(chunk.decode(encoding, "replace"))
            if out:
                restored.write(out)
                restored.flush()
        rest = filt.flush_rest()
        if rest:
            restored.write(rest)
            restored.flush()

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        yield
    finally:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        os.dup2(saved_fd, stdout_fd)
        thread.join(timeout=5)
        restored.close()
        os.close(saved_fd)
        os.close(pipe_r)


def compose_extra_functionality(*callbacks):
    """PyPSA n.optimize takes one extra_functionality hook; call several in order."""

    def extra_functionality(n, snapshots):
        for cb in callbacks:
            if cb is not None:
                cb(n, snapshots)

    return extra_functionality


# --- Resource adequacy ---

def coincident_peak_zonal_loads(year: int) -> tuple[float, pd.Timestamp, pd.Series]:
    """Statewide coincident peak MW, timestamp, and six zonal MW at that hour (full-year 8760)."""
    load_shape_reconciliation = importlib.import_module("02_load_shape_reconciliation")
    load = load_shape_reconciliation.reconcile_load_shape(year)
    zones = pd.read_csv(ZONE_BA_MAP_PATH)["zone"].tolist()
    missing = [z for z in zones if z not in load.columns]
    if missing:
        raise ValueError(f"reconciled load missing CO zones {missing}")
    total = load[zones].sum(axis=1)
    ts = total.idxmax()
    zonal = load.loc[ts, zones].astype(float)
    zonal.index.name = "zone"
    return float(total.loc[ts]), pd.Timestamp(ts), zonal


def statewide_coincident_peak(year: int) -> tuple[float, pd.Timestamp]:
    """Max of the six CO zonal loads summed each hour on the full-year reconciled 8760."""
    peak_mw, peak_ts, _ = coincident_peak_zonal_loads(year)
    return peak_mw, peak_ts


def statewide_prm_pct(year: int) -> float:
    """One statewide PRM; PSCo and WACM rows must match."""
    df = pd.read_csv(BA_RESERVE_MARGIN_PATH)
    sub = df.loc[df["year"] == year, "reference_margin_pct"]
    if sub.empty:
        raise ValueError(f"No reserve margin rows for year {year} in {BA_RESERVE_MARGIN_PATH}")
    vals = pd.unique(sub.to_numpy())
    if len(vals) != 1:
        raise ValueError(
            f"PSCo and WACM reference_margin_pct differ in {year}: {vals.tolist()}"
        )
    return float(vals[0])


def _elcc_pct(resource_set: str, technology: str, year: int) -> float:
    lookup = pd.read_csv(ELCC_LOOKUP_PATH)
    sub = lookup[
        (lookup["resource_set"] == resource_set) & (lookup["technology"] == technology)
    ]
    if sub.empty:
        raise ValueError(
            f"elcc_lookup.csv has no rows for resource_set={resource_set!r} "
            f"technology={technology!r}"
        )
    exact = sub.loc[sub["year"] == year, "accredited_capacity_pct"]
    if len(exact):
        return float(exact.iloc[0])
    below = sub.loc[sub["year"] < year]
    above = sub.loc[sub["year"] > year]
    if below.empty or above.empty:
        raise ValueError(
            f"Cannot interpolate ELCC for {resource_set}/{technology} year={year}; "
            f"available years={sorted(sub['year'].astype(int).tolist())}"
        )
    y0 = int(below["year"].max())
    y1 = int(above["year"].min())
    p0 = float(below.loc[below["year"] == y0, "accredited_capacity_pct"].iloc[0])
    p1 = float(above.loc[above["year"] == y1, "accredited_capacity_pct"].iloc[0])
    return p0 + (p1 - p0) * (year - y0) / (y1 - y0)


def _existing_dispatchable_credits(
    year: int, *, aggregate_large_cc: bool = False,
) -> dict[str, float]:
    resource_assembly = importlib.import_module("04_resource_assembly")
    active = resource_assembly.active_existing_resources(
        year, aggregate_large_cc=aggregate_large_cc,
    )
    out: dict[str, float] = {}
    for _, row in active.iterrows():
        if row["TechType"] in ELCC_CARRIERS:
            continue
        pct = row.get("accredited_capacity_pct")
        if pd.isna(pct):
            continue
        out[str(row["Name"])] = float(pct)
    return out


def _candidate_dispatchable_credits() -> dict[str, float]:
    params = pd.read_csv(CANDIDATE_PARAMS_PATH)
    out: dict[str, float] = {}
    for _, row in params.iterrows():
        tech = row["tech_class"]
        if tech in ELCC_CARRIERS or tech == "Solar+Storage":
            continue
        pct = row["accredited_capacity_pct"]
        if pd.isna(pct):
            continue
        out[str(tech)] = float(pct)
    return out


def _is_candidate_or_vintage(name: str) -> bool:
    return name.startswith("Candidate_") or name.startswith("Built_")


def accredited_fractions(
    n, year: int, *, aggregate_large_cc: bool = False,
) -> dict[str, float]:
    """credit as a 0-1 fraction for each CO-zone unit that counts toward PRM."""
    co_zones = set(pd.read_csv(ZONE_BA_MAP_PATH)["zone"])
    existing_disp = _existing_dispatchable_credits(
        year, aggregate_large_cc=aggregate_large_cc,
    )
    cand_disp = _candidate_dispatchable_credits()
    out: dict[str, float] = {}
    missing: list[str] = []
    for table in (n.generators, n.storage_units):
        if table.empty:
            continue
        for name, row in table.iterrows():
            if row["bus"] not in co_zones:
                continue
            if row["carrier"] == IMPORT_CARRIER:
                continue
            carrier = row["carrier"]
            if carrier == HYBRID_CARRIER:
                # Battery half gets candidate Solar+Storage ELCC (battery mar_cc).
                # Solar half is 0 — crediting both would double-count.
                if name in n.storage_units.index:
                    out[name] = _elcc_pct("candidate", HYBRID_CARRIER, year) / 100.0
                else:
                    out[name] = 0.0
                continue
            if carrier in ELCC_CARRIERS:
                resource_set = "candidate" if _is_candidate_or_vintage(name) else "existing"
                out[name] = _elcc_pct(resource_set, carrier, year) / 100.0
                continue
            if _is_candidate_or_vintage(name):
                if carrier not in cand_disp:
                    missing.append(name)
                    continue
                out[name] = cand_disp[carrier] / 100.0
                continue
            if name not in existing_disp:
                missing.append(name)
                continue
            out[name] = existing_disp[name] / 100.0
    if missing:
        raise ValueError(
            f"No accredited_capacity_pct for CO-zone units in {year}: {missing}"
        )
    if not out:
        raise ValueError(f"RA credit join produced no units for {year}")
    return out


def _p_nom_term(n, component: str, name: str, frac: float, extendable: bool, p_nom: float):
    if not extendable:
        return frac * float(p_nom)
    var = n.model[f"{component}-p_nom"]
    dim = var.dims[0]
    return var.sel({dim: name}) * frac


def _internal_ra_pipes() -> pd.DataFrame:
    """Internal firm pipes: name, from_zone, to_zone, transfer_limit_mw. Zeros are real N-1."""
    limits = pd.read_csv(TRANSFER_LIMITS_PATH)
    internal = limits.loc[limits["boundary_type"] == "internal"].copy()
    if internal.empty:
        raise ValueError(f"No internal rows in {TRANSFER_LIMITS_PATH}")
    if "transfer_limit_mw" not in internal.columns:
        raise ValueError(f"{TRANSFER_LIMITS_PATH} has no transfer_limit_mw column")
    mw = internal["transfer_limit_mw"].astype(float)
    if mw.isna().any():
        bad = internal.loc[mw.isna(), ["from_zone", "to_zone"]]
        raise ValueError(f"transfer_limit_mw is NaN for internal pairs:\n{bad}")
    if (mw < 0).any():
        bad = internal.loc[mw < 0, ["from_zone", "to_zone", "transfer_limit_mw"]]
        raise ValueError(f"transfer_limit_mw is negative for internal pairs:\n{bad}")
    external_buses = set(EXPECTED_EXTERNAL_BUSES)
    spilled = (
        set(internal["from_zone"]).intersection(external_buses)
        | set(internal["to_zone"]).intersection(external_buses)
    )
    if spilled:
        raise ValueError(f"internal RA pipe touches an external bus: {sorted(spilled)}")
    pipes = pd.DataFrame({
        "pipe": [
            f"RA_pipe_{row.from_zone}_{row.to_zone}" for row in internal.itertuples()
        ],
        "from_zone": internal["from_zone"].to_numpy(),
        "to_zone": internal["to_zone"].to_numpy(),
        "transfer_limit_mw": mw.to_numpy(),
    }).reset_index(drop=True)
    got_zeros = set(zip(pipes["from_zone"], pipes["to_zone"]))
    missing_zeros = ZERO_FIRM_PAIRS - got_zeros
    if missing_zeros:
        raise ValueError(
            f"expected N-1 zero pairs {sorted(ZERO_FIRM_PAIRS)} not in internal rows: "
            f"{sorted(missing_zeros)}"
        )
    return pipes


def _constraint_dual(n, name: str) -> float | None:
    try:
        dual = n.model.constraints[name].dual
        return float(dual.item() if hasattr(dual, "item") else dual)
    except Exception:
        try:
            dual_da = n.model.dual[name]
            return float(dual_da.item() if hasattr(dual_da, "item") else dual_da)
        except Exception:
            return None


def _solved_p_nom_mw(row) -> float:
    if row["p_nom_extendable"]:
        return float(row["p_nom_opt"]) if row["p_nom_opt"] > P_NOM_OPT_MIN else 0.0
    return float(row["p_nom"])


def make_reserve_margin(year: int, *, aggregate_large_cc: bool = False):
    """Factory: returns extra_functionality(n, snapshots) adding reserve_margin_CO."""
    prm_pct = statewide_prm_pct(year)
    peak_mw, peak_ts = statewide_coincident_peak(year)
    requirement = (1.0 + prm_pct / 100.0) * peak_mw
    print(
        f"  RA: peak={peak_mw:,.1f} MW at {peak_ts}  PRM={prm_pct:.1f}%  "
        f"requirement={requirement:,.1f} MW",
        flush=True,
    )

    def extra_functionality(n, snapshots):
        credits = accredited_fractions(n, year, aggregate_large_cc=aggregate_large_cc)
        lhs = None
        for component, table in (("Generator", n.generators), ("StorageUnit", n.storage_units)):
            if table.empty:
                continue
            for name, row in table.iterrows():
                if name not in credits:
                    continue
                term = _p_nom_term(
                    n,
                    component,
                    name,
                    credits[name],
                    bool(row["p_nom_extendable"]),
                    float(row["p_nom"]),
                )
                lhs = term if lhs is None else lhs + term
        if lhs is None:
            raise ValueError(f"reserve_margin_CO has empty LHS in {year}")
        n.model.add_constraints(lhs >= requirement, name="reserve_margin_CO")

    return extra_functionality


def print_reserve_margin_table(
    n, year: int, *, aggregate_large_cc: bool = True,
) -> dict:
    """Post-solve accredited MW vs requirement (uses p_nom_opt for new-build)."""
    prm_pct = statewide_prm_pct(year)
    peak_mw, peak_ts = statewide_coincident_peak(year)
    requirement = (1.0 + prm_pct / 100.0) * peak_mw
    credits = accredited_fractions(n, year, aggregate_large_cc=aggregate_large_cc)
    rows = []
    for component, table in (("Generator", n.generators), ("StorageUnit", n.storage_units)):
        if table.empty:
            continue
        for name, row in table.iterrows():
            if name not in credits:
                continue
            if row["p_nom_extendable"]:
                mw = float(row["p_nom_opt"]) if row["p_nom_opt"] > P_NOM_OPT_MIN else 0.0
            else:
                mw = float(row["p_nom"])
            rows.append({
                "carrier": row["carrier"],
                "accredited_mw": mw * credits[name],
                "p_nom": mw,
            })
    stacked = pd.DataFrame(rows)
    by_carrier = stacked.groupby("carrier")[["accredited_mw", "p_nom"]].sum()
    total = float(by_carrier["accredited_mw"].sum())
    slack = total - requirement
    print("Reserve margin (statewide, copper-plate):", flush=True)
    print(
        f"  peak {peak_mw:,.1f} MW at {peak_ts}  PRM {prm_pct:.1f}%  "
        f"requirement {requirement:,.1f} MW",
        flush=True,
    )
    print(by_carrier.to_string(float_format=lambda x: f"{x:,.1f}"), flush=True)
    print(f"  accredited total {total:,.1f} MW  slack {slack:,.1f} MW", flush=True)
    dual = _constraint_dual(n, "reserve_margin_CO")
    if dual is not None:
        print(f"  dual ${dual:,.2f}/MW-yr", flush=True)
    return {
        "year": year,
        "peak_mw": peak_mw,
        "peak_ts": str(peak_ts),
        "prm_pct": prm_pct,
        "requirement_mw": requirement,
        "accredited_mw": total,
        "slack_mw": slack,
        "dual": dual if dual is not None else float("nan"),
    }


def make_zonal_ra_pipes(year: int, *, aggregate_large_cc: bool = False):
    """Factory: RA-only firm pipes + six zonal deliverability inequalities at t*."""
    pipes = _internal_ra_pipes()
    peak_mw, peak_ts, zonal_load = coincident_peak_zonal_loads(year)
    zones = list(zonal_load.index)
    print(
        f"  RA pipes: t*={peak_ts}  statewide peak={peak_mw:,.1f} MW  "
        f"{len(pipes)} internal interfaces",
        flush=True,
    )
    for row in pipes.itertuples():
        zero_tag = "  (N-1 zero)" if row.transfer_limit_mw == 0.0 else ""
        print(
            f"    {row.pipe}: {row.from_zone} <-> {row.to_zone}  "
            f"+/-{row.transfer_limit_mw:,.1f} MW{zero_tag}",
            flush=True,
        )
    print("  zonal load at t*:", flush=True)
    for zone in zones:
        print(f"    {zone}: {float(zonal_load[zone]):,.1f} MW", flush=True)

    def extra_functionality(n, snapshots):
        n.model.add_variables(
            lower=-pipes["transfer_limit_mw"].to_numpy(),
            upper=pipes["transfer_limit_mw"].to_numpy(),
            coords=[pd.Index(pipes["pipe"].tolist(), name="RA_pipe")],
            name="RA_pipe",
        )
        flow = n.model["RA_pipe"]
        credits = accredited_fractions(n, year, aggregate_large_cc=aggregate_large_cc)
        for zone in zones:
            lhs = None
            for component, table in (
                ("Generator", n.generators),
                ("StorageUnit", n.storage_units),
            ):
                if table.empty:
                    continue
                for name, row in table.iterrows():
                    if name not in credits or row["bus"] != zone:
                        continue
                    term = _p_nom_term(
                        n,
                        component,
                        name,
                        credits[name],
                        bool(row["p_nom_extendable"]),
                        float(row["p_nom"]),
                    )
                    lhs = term if lhs is None else lhs + term
            for row in pipes.itertuples():
                f = flow.sel(RA_pipe=row.pipe)
                if row.to_zone == zone:
                    lhs = f if lhs is None else lhs + f
                if row.from_zone == zone:
                    lhs = -f if lhs is None else lhs - f
            if lhs is None:
                raise ValueError(f"RA_deliverability_{zone} has empty LHS in {year}")
            n.model.add_constraints(
                lhs >= float(zonal_load[zone]),
                name=f"RA_deliverability_{zone}",
            )

    return extra_functionality


def print_zonal_ra_table(
    n, year: int, *, aggregate_large_cc: bool = True,
) -> pd.DataFrame:
    """Post-solve zonal accredited MW, net firm import, pipe flows, and duals."""
    pipes = _internal_ra_pipes()
    peak_mw, peak_ts, zonal_load = coincident_peak_zonal_loads(year)
    zones = list(zonal_load.index)
    credits = accredited_fractions(n, year, aggregate_large_cc=aggregate_large_cc)
    accredited = {z: 0.0 for z in zones}
    for table in (n.generators, n.storage_units):
        if table.empty:
            continue
        for name, row in table.iterrows():
            if name not in credits:
                continue
            zone = row["bus"]
            if zone not in accredited:
                continue
            accredited[zone] += _solved_p_nom_mw(row) * credits[name]

    if "RA_pipe" not in n.model.variables:
        raise ValueError("RA_pipe variables missing after zonal_ra solve")
    sol = n.model["RA_pipe"].solution
    flows = {}
    for pipe in pipes["pipe"]:
        val = sol.sel(RA_pipe=pipe)
        flows[pipe] = float(val.item() if hasattr(val, "item") else val)

    external_buses = set(EXPECTED_EXTERNAL_BUSES)
    bad_ext = [
        row.pipe
        for row in pipes.itertuples()
        if row.from_zone in external_buses or row.to_zone in external_buses
    ]
    if bad_ext:
        raise ValueError(f"RA_pipe names involve an external bus: {bad_ext}")

    net_firm = {z: 0.0 for z in zones}
    for row in pipes.itertuples():
        f = flows[row.pipe]
        pair = (row.from_zone, row.to_zone)
        rev = (row.to_zone, row.from_zone)
        if (pair in ZERO_FIRM_PAIRS or rev in ZERO_FIRM_PAIRS) and abs(f) > 1e-6:
            raise ValueError(f"{row.pipe} is an N-1 zero but solved flow={f}")
        net_firm[row.from_zone] -= f
        net_firm[row.to_zone] += f

    print("Zonal deliverability (firm RA pipes at t*):", flush=True)
    print(f"  t* {peak_ts}  statewide peak {peak_mw:,.1f} MW", flush=True)
    zone_rows = []
    for zone in zones:
        load_z = float(zonal_load[zone])
        acc = accredited[zone]
        net = net_firm[zone]
        slack = acc + net - load_z
        dual = _constraint_dual(n, f"RA_deliverability_{zone}")
        zone_rows.append({
            "zone": zone,
            "accredited_mw": acc,
            "net_firm_in_mw": net,
            "load_at_tstar_mw": load_z,
            "slack_mw": slack,
            "dual": dual if dual is not None else float("nan"),
        })
    zone_df = pd.DataFrame(zone_rows).set_index("zone")
    print(zone_df.to_string(float_format=lambda x: f"{x:,.1f}"), flush=True)

    pipe_rows = []
    for row in pipes.itertuples():
        f = flows[row.pipe]
        pipe_rows.append({
            "pipe": row.pipe,
            "from": row.from_zone,
            "to": row.to_zone,
            "flow_mw": f,
            "limit_mw": row.transfer_limit_mw,
            "at_bound": abs(abs(f) - row.transfer_limit_mw) < 0.5
            if row.transfer_limit_mw > 0
            else abs(f) < 1e-6,
        })
    pipe_df = pd.DataFrame(pipe_rows).set_index("pipe")
    print("RA pipe flows (positive = from -> to):", flush=True)
    print(pipe_df.to_string(float_format=lambda x: f"{x:,.1f}"), flush=True)
    prm_dual = _constraint_dual(n, "reserve_margin_CO")
    if prm_dual is not None:
        print(f"  reserve_margin_CO dual ${prm_dual:,.2f}/MW-yr", flush=True)
    zone_out = zone_df.reset_index()
    zone_out.insert(0, "kind", "zone")
    zone_out = zone_out.rename(columns={"zone": "name"})
    pipe_out = pipe_df.reset_index()
    pipe_out.insert(0, "kind", "pipe")
    pipe_out = pipe_out.rename(columns={"pipe": "name"})
    combined = pd.concat([zone_out, pipe_out], ignore_index=True, sort=False)
    combined.insert(0, "year", year)
    return combined


# --- CO2 cap ---

def annual_co2_cap_mmt(year: int, co2_path: str = "statutory") -> float:
    """Absolute MMT cap. Baseline tons are always Script 26's 42.023.

    co2_path="statutory" reads data_cleaning/policy/co2_target.csv (do not edit that
    file for a case). Any other name reads data_cleaning/policy/co2_paths/{name}.csv
    (columns: year, co2_reduction_pct_vs_2005). Missing file is a hard error.
    cap = 42.023 * (1 - pct/100).
    """
    if co2_path == "statutory":
        df = pd.read_csv(CO2_TARGET_PATH)
        row = df.loc[df["year"] == year]
        if row.empty:
            raise ValueError(f"No CO2 target row for year {year} in {CO2_TARGET_PATH}")
        if len(row) != 1:
            raise ValueError(f"Duplicate CO2 target rows for year {year} in {CO2_TARGET_PATH}")
        baseline = float(row["co2_baseline_2005_mmt_co2"].iloc[0])
        if abs(baseline - CO2_BASELINE_2005_MMT) > 1e-9:
            raise ValueError(
                f"co2_baseline_2005_mmt_co2 is {baseline} in {year}; expected {CO2_BASELINE_2005_MMT}"
            )
        pct = float(row["co2_reduction_pct_vs_2005"].iloc[0])
        if pd.isna(pct):
            raise ValueError(f"co2_reduction_pct_vs_2005 is missing for year {year}")
        return baseline * (1.0 - pct / 100.0)

    path = CO2_PATHS_DIR / f"{co2_path}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"CO2 path {co2_path!r} not found at {path}. "
            f"'statutory' reads {CO2_TARGET_PATH}; other names need "
            f"{CO2_PATHS_DIR / '{name}.csv'}"
        )
    df = pd.read_csv(path)
    missing_cols = [c for c in ("year", "co2_reduction_pct_vs_2005") if c not in df.columns]
    if missing_cols:
        raise ValueError(f"{path} missing columns {missing_cols}")
    row = df.loc[df["year"] == year]
    if row.empty:
        raise ValueError(f"No CO2 path row for year {year} in {path}")
    if len(row) != 1:
        raise ValueError(f"Duplicate CO2 path rows for year {year} in {path}")
    pct = float(row["co2_reduction_pct_vs_2005"].iloc[0])
    if pd.isna(pct):
        raise ValueError(f"co2_reduction_pct_vs_2005 is missing for year {year} in {path}")
    return CO2_BASELINE_2005_MMT * (1.0 - pct / 100.0)


def _co2_cap_metric_tons(year: int, co2_path: str = "statutory") -> float:
    """LP RHS: cap_mmt * 1e6. Files stay lb/MWh; convert rates when building co2_CO."""
    return annual_co2_cap_mmt(year, co2_path=co2_path) * 1e6


def _candidate_co2_lb_per_mwh() -> dict[str, float]:
    params = pd.read_csv(CANDIDATE_PARAMS_PATH)
    if "co2_lb_per_mwh" not in params.columns:
        raise ValueError(f"{CANDIDATE_PARAMS_PATH} has no co2_lb_per_mwh column")
    out: dict[str, float] = {}
    for _, row in params.iterrows():
        val = row["co2_lb_per_mwh"]
        if pd.isna(val):
            raise ValueError(f"co2_lb_per_mwh is NaN for tech_class={row['tech_class']}")
        out[str(row["tech_class"])] = float(val)
    return out


def _gas_cc_co2_lb_per_mwh() -> float:
    rates = _candidate_co2_lb_per_mwh()
    if "Gas:CC" not in rates:
        raise ValueError("Candidate Gas:CC missing co2_lb_per_mwh")
    return rates["Gas:CC"]


def _generator_dispatch_var(n):
    """Generator-p and its non-snapshot dimension name (PyPSA uses 'Generator')."""
    p = n.model["Generator-p"]
    dims = [d for d in p.dims if d != "snapshot"]
    if len(dims) != 1:
        raise ValueError(f"Generator-p dims unexpected: {p.dims}")
    return p, dims[0]


def _market_generator_names(n) -> list[str]:
    return [
        name
        for name, row in n.generators.iterrows()
        if row["carrier"] == IMPORT_CARRIER
    ]


def emissions_rate_lb_per_mwh(
    n, year: int, *, aggregate_large_cc: bool = False,
) -> dict[str, float]:
    """Electrical lb/MWh for every in-state Generator and every Market_*. StorageUnits omitted."""
    resource_assembly = importlib.import_module("04_resource_assembly")
    active = resource_assembly.active_existing_resources(
        year, aggregate_large_cc=aggregate_large_cc,
    )
    if "co2_RelRateMWh" not in active.columns:
        raise ValueError("assembled existing fleet has no co2_RelRateMWh column")
    by_name = active.set_index("Name")["co2_RelRateMWh"]
    cand = _candidate_co2_lb_per_mwh()
    cc_rate = _gas_cc_co2_lb_per_mwh()
    co_zones = set(pd.read_csv(ZONE_BA_MAP_PATH)["zone"])
    out: dict[str, float] = {}
    missing: list[str] = []
    for name, row in n.generators.iterrows():
        carrier = row["carrier"]
        if carrier == IMPORT_CARRIER:
            out[name] = cc_rate
            continue
        if row["bus"] not in co_zones:
            missing.append(name)
            continue
        if _is_candidate_or_vintage(name):
            if carrier not in cand:
                missing.append(name)
                continue
            out[name] = cand[carrier]
            continue
        if name not in by_name.index:
            missing.append(name)
            continue
        val = by_name.loc[name]
        if pd.isna(val):
            missing.append(name)
            continue
        out[name] = float(val)
    if missing:
        raise ValueError(f"No co2 rate for generators in {year}: {missing}")
    expected = set(n.generators.index)
    got = set(out)
    if expected != got:
        raise ValueError(
            f"emissions_rate_lb_per_mwh coverage mismatch in {year}: "
            f"missing={sorted(expected - got)} extra={sorted(got - expected)}"
        )
    storage_hit = [s for s in n.storage_units.index if s in out]
    if storage_hit:
        raise ValueError(f"StorageUnits must not be in the CO2 rate dict: {storage_hit}")
    return out


def make_co2_cap(year: int, *, aggregate_large_cc: bool = True, co2_path: str = "statutory"):
    """Factory: returns extra_functionality(n, snapshots) adding co2_CO.

    Inequality is in metric tons (dual = $/t). Stored rates stay lb/MWh.
    No Market_* (island): skip CO2_import_flow and count in-state generation only.
    """
    cap_mmt = annual_co2_cap_mmt(year, co2_path=co2_path)
    cap_t = _co2_cap_metric_tons(year, co2_path=co2_path)
    cc_rate = _gas_cc_co2_lb_per_mwh()
    print(
        f"  CO2: cap={cap_mmt:.4f} MMT ({cap_t:,.0f} t)  path={co2_path}  "
        f"import intensity={cc_rate:.1f} lb/MWh (Candidate_Gas:CC)",
        flush=True,
    )

    def extra_functionality(n, snapshots):
        rates = emissions_rate_lb_per_mwh(n, year, aggregate_large_cc=aggregate_large_cc)
        p, gen_dim = _generator_dispatch_var(n)
        markets = _market_generator_names(n)
        imp = None
        if markets:
            coords = []
            for dim in p.dims:
                if dim == "snapshot":
                    coords.append(n.snapshots)
                else:
                    coords.append(pd.Index(markets, name=dim))
            n.model.add_variables(lower=0, coords=coords, name=CO2_IMPORT_FLOW)
            imp = n.model[CO2_IMPORT_FLOW]
            p_mkt = p.sel({gen_dim: markets})
            n.model.add_constraints(imp >= p_mkt, name="CO2_import_ge_p")
        else:
            print("  CO2: in-state only (no Market_* / import flow)", flush=True)
        w = n.snapshot_weightings["generators"].reindex(n.snapshots).astype(float)
        lhs = None
        for name, rate_lb in rates.items():
            if rate_lb == 0.0:
                continue
            rate_t = rate_lb / LB_PER_METRIC_TON
            if n.generators.at[name, "carrier"] == IMPORT_CARRIER:
                if imp is None:
                    raise ValueError(f"Market generator {name} present but CO2_import_flow was skipped")
                expr = (imp.sel({gen_dim: name}) * w.to_numpy() * rate_t).sum()
            else:
                expr = (p.sel({gen_dim: name}) * w.to_numpy() * rate_t).sum()
            lhs = expr if lhs is None else lhs + expr
        if lhs is None:
            lhs = 0.0 * p.isel({gen_dim: 0}).sum()
        n.model.add_constraints(lhs <= cap_t, name=CO2_CONSTRAINT)

    return extra_functionality


def print_co2_table(
    n, year: int, *, aggregate_large_cc: bool = True, co2_path: str = "statutory",
) -> dict:
    """Post-solve in-state vs attributed-import CO2 vs cap; dual labeled $/metric ton."""
    rates = emissions_rate_lb_per_mwh(n, year, aggregate_large_cc=aggregate_large_cc)
    storage_hit = [s for s in n.storage_units.index if s in rates]
    if storage_hit:
        raise ValueError(f"StorageUnits must not be in the CO2 rate dict: {storage_hit}")
    cap_mmt = annual_co2_cap_mmt(year, co2_path=co2_path)
    w = n.snapshot_weightings["generators"].reindex(n.snapshots).astype(float)
    p_t = n.generators_t.p
    in_state_lb = 0.0
    import_lb = 0.0
    import_mwh = 0.0
    markets = _market_generator_names(n)
    for name, rate in rates.items():
        if name not in p_t.columns:
            raise ValueError(f"solved Generator-p missing {name}")
        if n.generators.at[name, "carrier"] == IMPORT_CARRIER:
            pos = float((p_t[name].clip(lower=0) * w).sum())
            import_mwh += pos
            import_lb += pos * rate
        else:
            in_state_lb += float((p_t[name] * w).sum()) * rate

    if markets:
        if CO2_IMPORT_FLOW not in n.model.variables:
            raise ValueError("CO2_import_flow variables missing after co2_cap solve")
        sol = n.model[CO2_IMPORT_FLOW].solution
        gen_dim = [d for d in sol.dims if d != "snapshot"][0]
        for name in markets:
            flow = sol.sel({gen_dim: name}).to_pandas().reindex(n.snapshots)
            expected = p_t[name].clip(lower=0).reindex(n.snapshots)
            gap = (flow.astype(float) - expected.astype(float)).abs().max()
            if gap > 0.1:
                raise ValueError(
                    f"{name}: import_flow vs max(p,0) max |gap|={gap:.3f} MW (export credit?)"
                )
    elif CO2_IMPORT_FLOW in n.model.variables:
        raise ValueError("CO2_import_flow present but no Market_* generators")

    total_lb = in_state_lb + import_lb
    total_mmt = total_lb / (1e6 * LB_PER_METRIC_TON)
    in_state_mmt = in_state_lb / (1e6 * LB_PER_METRIC_TON)
    import_mmt = import_lb / (1e6 * LB_PER_METRIC_TON)
    slack_mmt = cap_mmt - total_mmt
    if markets:
        print("CO2 cap (annual, production + attributed imports):", flush=True)
    else:
        print("CO2 cap (annual, in-state only):", flush=True)
    print(
        f"  cap {cap_mmt:.4f} MMT  solved {total_mmt:.4f} MMT  "
        f"in-state {in_state_mmt:.4f}  imports {import_mmt:.4f}  slack {slack_mmt:.4f}",
        flush=True,
    )
    print(f"  import energy {import_mwh:,.0f} MWh (positive Market.p only)", flush=True)
    dual_t = _constraint_dual(n, CO2_CONSTRAINT)
    if dual_t is not None:
        print(
            f"  dual ${dual_t:,.2f}/metric ton  (native on {CO2_CONSTRAINT})",
            flush=True,
        )
    return {
        "year": year,
        "co2_path": co2_path,
        "cap_mmt": cap_mmt,
        "solved_mmt": total_mmt,
        "in_state_mmt": in_state_mmt,
        "import_mmt": import_mmt,
        "slack_mmt": slack_mmt,
        "import_mwh": import_mwh,
        "dual": dual_t if dual_t is not None else float("nan"),
    }


def _hybrid_constraint_tag(name: str) -> str:
    return str(name).replace("+", "_plus_").replace(":", "_")


def _hybrid_pairs(n) -> list[tuple[str, str, bool]]:
    """(solar_name, battery_name, extendable) for every Solar+Storage pair."""
    if n.storage_units.empty:
        return []
    hybrid_sto = n.storage_units[n.storage_units["carrier"] == HYBRID_CARRIER]
    pairs: list[tuple[str, str, bool]] = []
    missing_solar: list[str] = []
    for batt, row in hybrid_sto.iterrows():
        solar = hybrid_solar_name_for_battery(batt)
        if solar not in n.generators.index:
            missing_solar.append(batt)
            continue
        if n.generators.at[solar, "carrier"] != HYBRID_CARRIER:
            raise ValueError(
                f"hybrid battery {batt} pairs with {solar} "
                f"carrier={n.generators.at[solar, 'carrier']!r}, expected {HYBRID_CARRIER}"
            )
        batt_ext = bool(row["p_nom_extendable"])
        solar_ext = bool(n.generators.at[solar, "p_nom_extendable"])
        if batt_ext != solar_ext:
            raise ValueError(
                f"hybrid pair extendable mismatch: {solar}={solar_ext} vs {batt}={batt_ext}"
            )
        pairs.append((solar, batt, batt_ext))
    if missing_solar:
        raise ValueError(f"hybrid StorageUnit has no paired Generator: {missing_solar}")
    hybrid_gen = n.generators[n.generators["carrier"] == HYBRID_CARRIER]
    orphan = [
        solar for solar in hybrid_gen.index
        if hybrid_battery_name_for_solar(solar) not in n.storage_units.index
    ]
    if orphan:
        raise ValueError(f"hybrid Generator has no paired StorageUnit: {orphan}")
    return pairs


def make_hybrid_pairing():
    """Factory: p_nom_batt = 0.6 * p_nom_solar (extendable) and p_store(t) <= p_solar(t)."""

    def extra_functionality(n, snapshots):
        pairs = _hybrid_pairs(n)
        if not pairs:
            raise ValueError(
                "hybrid_candidates=True but no Solar+Storage pairs on the network"
            )
        p_gen, gen_dim = _generator_dispatch_var(n)
        p_store = n.model["StorageUnit-p_store"]
        sto_dims = [d for d in p_store.dims if d != "snapshot"]
        if len(sto_dims) != 1:
            raise ValueError(f"StorageUnit-p_store dims unexpected: {p_store.dims}")
        sto_dim = sto_dims[0]
        n_charge = 0
        n_pair = 0
        for solar, batt, extendable in pairs:
            tag = _hybrid_constraint_tag(batt)
            n.model.add_constraints(
                p_store.sel({sto_dim: batt}) <= p_gen.sel({gen_dim: solar}),
                name=f"hybrid_charge_from_solar_{tag}",
            )
            n_charge += 1
            if not extendable:
                continue
            gen_p_nom = n.model["Generator-p_nom"]
            sto_p_nom = n.model["StorageUnit-p_nom"]
            n.model.add_constraints(
                sto_p_nom.sel({sto_p_nom.dims[0]: batt})
                == HYBRID_BATTERY_MW_PER_SOLAR_MW * gen_p_nom.sel({gen_p_nom.dims[0]: solar}),
                name=f"hybrid_pair_p_nom_{tag}",
            )
            n_pair += 1
        print(
            f"  hybrid: {len(pairs)} pairs  "
            f"p_nom equality on {n_pair} extendable  "
            f"charge-from-solar on {n_charge}",
            flush=True,
        )

    return extra_functionality


# --- Myopic solve loop ---

def optimize_highs(
    n,
    periods,
    year: int,
    *,
    step: int | None = None,
    n_years: int | None = None,
    reserve_margin: bool = True,
    zonal_ra: bool = True,
    co2_cap: bool = True,
    relax_pmin: bool = True,
    aggregate_large_cc: bool = True,
    hybrid_candidates: bool = True,
    co2_path: str = "statutory",
):
    """HiGHS dual simplex, threads=2, week-cyclic SOC.

    include_objective_constant=False: existing-fleet capital is not a decision
    variable; leaving it in the LP hurts conditioning (PyPSA 2.0 default).
    Year banner is injected above HiGHS's Iteration table (and tagged on each row)
    so a live terminal does not require scrolling back through build_network.

    Omitting a policy flag keeps the core (all True). zonal_ra requires
    reserve_margin=True. co2_path is the named percent series when co2_cap is on.
    """
    if zonal_ra and not reserve_margin:
        raise ValueError("zonal_ra requires reserve_margin=True")
    if relax_pmin:
        _relax_instate_generator_pmin(n, log=False)
    extra = make_week_cyclic_soc(periods)
    if reserve_margin:
        extra = compose_extra_functionality(
            extra, make_reserve_margin(year, aggregate_large_cc=aggregate_large_cc),
        )
    if zonal_ra:
        extra = compose_extra_functionality(
            extra, make_zonal_ra_pipes(year, aggregate_large_cc=aggregate_large_cc),
        )
    if co2_cap:
        extra = compose_extra_functionality(
            extra, make_co2_cap(
                year, aggregate_large_cc=aggregate_large_cc, co2_path=co2_path,
            ),
        )
    if hybrid_candidates:
        extra = compose_extra_functionality(extra, make_hybrid_pairing())
    with highs_simplex_year_banner(year, step=step, n_years=n_years):
        return n.optimize(
            solver_name="highs",
            solver_options={"solver": "simplex", "threads": 2},
            extra_functionality=extra,
            include_objective_constant=False,
        )


def run_myopic_sequence(
    *,
    network_prefix: str,
    title: str,
    internal_limits: bool = True,
    neighbors: bool = True,
    reserve_margin: bool = True,
    zonal_ra: bool = True,
    co2_cap: bool = True,
    relax_pmin: bool = True,
    aggregate_large_cc: bool = True,
    hybrid_candidates: bool = True,
    co2_path: str = "statutory",
    resume_after_year: int | None = None,
) -> None:
    """Five sequential LPs (2030–2050) with vintage carry-forward.

    network_prefix is the subfolder under pypsa/scenarios/ (e.g. "core" ->
    scenarios/core/2030.nc and scenarios/core/capacity_by_year.csv). Nested
    groups work (`_dev_milestones/08c_hybrid`). A full terminal capture
    (stdout, stderr, HiGHS iterates) is written to scenarios/{prefix}/solve.log.

    Omitting a flag keeps the core. resume_after_year: if set (e.g. 2035), load
    that checkpoint, rebuild vintages from Built_* plus that year's Candidate_*
    p_nom_opt, keep CSV rows through that year, and solve the remaining
    investment years only. The solve log is appended rather than overwritten.
    """
    if zonal_ra and not reserve_margin:
        raise ValueError("zonal_ra requires reserve_margin=True")
    with tee_solve_log(network_prefix, append=resume_after_year is not None):
        _run_myopic_sequence_impl(
            network_prefix=network_prefix,
            title=title,
            internal_limits=internal_limits,
            neighbors=neighbors,
            reserve_margin=reserve_margin,
            zonal_ra=zonal_ra,
            co2_cap=co2_cap,
            relax_pmin=relax_pmin,
            aggregate_large_cc=aggregate_large_cc,
            hybrid_candidates=hybrid_candidates,
            co2_path=co2_path,
            resume_after_year=resume_after_year,
        )


def _csv_through_year(path, year: int) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "year" in df.columns:
        df = df[df["year"] <= year]
    return df


def _concat_write(parts: list[pd.DataFrame], path) -> None:
    frames = [f for f in parts if f is not None and len(f)]
    if not frames:
        return
    pd.concat(frames, ignore_index=True).to_csv(path, index=False)


def _run_myopic_sequence_impl(
    *,
    network_prefix: str,
    title: str,
    internal_limits: bool = True,
    neighbors: bool = True,
    reserve_margin: bool = True,
    zonal_ra: bool = True,
    co2_cap: bool = True,
    relax_pmin: bool = True,
    aggregate_large_cc: bool = True,
    hybrid_candidates: bool = True,
    co2_path: str = "statutory",
    resume_after_year: int | None = None,
) -> None:
    if zonal_ra and not reserve_margin:
        raise ValueError("zonal_ra requires reserve_margin=True")
    out_dir = run_output_dir(network_prefix)
    csv_path = run_capacity_csv_path(network_prefix)
    end_year = INVESTMENT_YEARS[-1]

    print(f"\n--- {title} ---", flush=True)
    print(f"Investment years: {INVESTMENT_YEARS}", flush=True)
    print(f"internal_limits={internal_limits}", flush=True)
    print(f"neighbors={neighbors}", flush=True)
    print(f"reserve_margin={reserve_margin}", flush=True)
    print(f"zonal_ra={zonal_ra}", flush=True)
    print(f"co2_cap={co2_cap}", flush=True)
    print(f"co2_path={co2_path}", flush=True)
    print(f"relax_pmin={relax_pmin}", flush=True)
    print(f"aggregate_large_cc={aggregate_large_cc}", flush=True)
    print(f"hybrid_candidates={hybrid_candidates}", flush=True)
    if resume_after_year is not None:
        print(f"resume_after_year={resume_after_year}", flush=True)
    print("HiGHS dual simplex, threads=2, include_objective_constant=False", flush=True)

    vintage_gen = _empty_vintage_generators()
    vintage_sto = _empty_vintage_storage()
    capacity_rows: list[dict] = []
    buildout_parts: list[pd.DataFrame] = []
    generation_parts: list[pd.DataFrame] = []
    charge_parts: list[pd.DataFrame] = []
    lmp_parts: list[pd.DataFrame] = []
    co2_parts: list[pd.DataFrame] = []
    interchange_parts: list[pd.DataFrame] = []
    gross_interchange_parts: list[pd.DataFrame] = []
    prm_parts: list[pd.DataFrame] = []
    zonal_parts: list[pd.DataFrame] = []
    summary_parts: list[pd.DataFrame] = []
    cost_parts: list[pd.DataFrame] = []
    years = list(INVESTMENT_YEARS)
    if resume_after_year is not None:
        if resume_after_year not in INVESTMENT_YEARS:
            raise ValueError(
                f"resume_after_year={resume_after_year} is not in {INVESTMENT_YEARS}"
            )
        idx = INVESTMENT_YEARS.index(resume_after_year)
        if idx == len(INVESTMENT_YEARS) - 1:
            raise ValueError(f"resume_after_year={resume_after_year} is the last year")
        years = INVESTMENT_YEARS[idx + 1 :]
        prev_path = run_checkpoint_path(network_prefix, resume_after_year)
        if not prev_path.exists():
            raise FileNotFoundError(f"Cannot resume: missing {prev_path}")
        pypsa = _import_installed_pypsa()
        n_prev = pypsa.Network(str(prev_path))
        resource_assembly = importlib.import_module("04_resource_assembly")
        cand_gen, cand_sto = resource_assembly.build_candidate_components(
            resume_after_year, hybrid_candidates=hybrid_candidates,
        )
        harvested_gen, harvested_sto = harvest_vintages(
            n_prev, cand_gen, cand_sto, resume_after_year,
        )
        carried_gen, carried_sto = carried_vintages_from_network(n_prev)
        vintage_gen = pd.concat([carried_gen, harvested_gen])
        vintage_sto = pd.concat([carried_sto, harvested_sto])
        if csv_path.exists():
            prior = pd.read_csv(csv_path)
            prior = prior[prior["year"] <= resume_after_year]
            capacity_rows = prior.to_dict("records")
        buildout_parts.append(_csv_through_year(out_dir / "buildout_by_year.csv", resume_after_year))
        generation_parts.append(_csv_through_year(out_dir / "generation_by_year.csv", resume_after_year))
        charge_parts.append(_csv_through_year(out_dir / "storage_charge_by_year.csv", resume_after_year))
        lmp_parts.append(_csv_through_year(out_dir / "lmp_by_year.csv", resume_after_year))
        co2_parts.append(_csv_through_year(out_dir / "co2_by_year.csv", resume_after_year))
        interchange_parts.append(
            _csv_through_year(out_dir / "interchange_by_year.csv", resume_after_year)
        )
        gross_interchange_parts.append(
            _csv_through_year(out_dir / "gross_interchange_by_year.csv", resume_after_year)
        )
        prm_parts.append(
            _csv_through_year(out_dir / "reserve_margin_by_year.csv", resume_after_year)
        )
        zonal_parts.append(_csv_through_year(out_dir / "zonal_ra_by_year.csv", resume_after_year))
        summary_parts.append(_csv_through_year(out_dir / "summary_by_year.csv", resume_after_year))
        cost_parts.append(_csv_through_year(out_dir / "cost_by_year.csv", resume_after_year))
        print(
            f"  resumed from {prev_path.name}: "
            f"{len(vintage_gen)} generator vintages, {len(vintage_sto)} storage vintages; "
            f"next year {years[0]}",
            flush=True,
        )

    n_years = len(INVESTMENT_YEARS)
    for year in years:
        step = INVESTMENT_YEARS.index(year) + 1
        print(f"\n=== YEAR {year}/{end_year} START (step {step}/{n_years}) ===", flush=True)

        extra_gen = surviving_vintages(vintage_gen, year)
        extra_sto = surviving_vintages(vintage_sto, year)
        print(
            f"  surviving vintages: {len(extra_gen)} generators, {len(extra_sto)} storage",
            flush=True,
        )

        n, generators, storage, periods = build_network(
            year,
            extra_fixed_generators=extra_gen if len(extra_gen) else None,
            extra_fixed_storage=extra_sto if len(extra_sto) else None,
            internal_limits=internal_limits,
            neighbors=neighbors,
            relax_pmin=relax_pmin,
            aggregate_large_cc=aggregate_large_cc,
            hybrid_candidates=hybrid_candidates,
        )

        extras = []
        if reserve_margin:
            extras.append("statewide PRM")
        if zonal_ra:
            extras.append("zonal RA pipes")
        if co2_cap:
            extras.append("CO2 cap")
        if relax_pmin:
            extras.append("relax_pmin")
        if aggregate_large_cc:
            extras.append("aggregate_large_cc")
        if hybrid_candidates:
            extras.append("hybrid_candidates")
        extra_label = f", {', '.join(extras)}" if extras else ""
        print(
            f"Solving {year} ({len(n.snapshots)} snapshots, week-cyclic SOC"
            f"{extra_label})...",
            flush=True,
        )
        start = time.time()
        status, condition = optimize_highs(
            n,
            periods,
            year,
            step=step,
            n_years=n_years,
            reserve_margin=reserve_margin,
            zonal_ra=zonal_ra,
            co2_cap=co2_cap,
            relax_pmin=relax_pmin,
            aggregate_large_cc=aggregate_large_cc,
            hybrid_candidates=hybrid_candidates,
            co2_path=co2_path,
        )
        elapsed = time.time() - start

        if status != "ok":
            print(
                f"=== YEAR {year} FAILED status={status}  condition={condition}  "
                f"wall={elapsed:.0f}s ===",
                flush=True,
            )
            print("Sequence aborted -- later years not started.", flush=True)
            sys.exit(1)

        new_gen, new_sto = harvest_vintages(n, generators, storage, year)
        vintage_gen = pd.concat([extra_gen, new_gen])
        vintage_sto = pd.concat([extra_sto, new_sto])
        n_carried = len(vintage_gen) + len(vintage_sto)

        print(
            f"=== YEAR {year} DONE status={status}  wall={elapsed:.0f}s  "
            f"objective=${n.objective:,.0f}  vintages_carried={n_carried} ===",
            flush=True,
        )
        print("Build-out by carrier (MW):", flush=True)
        buildout = print_buildout_table(n).reset_index()
        buildout.insert(0, "year", year)
        buildout_parts.append(buildout)
        _concat_write(buildout_parts, out_dir / "buildout_by_year.csv")

        gen_tbl = generation_by_carrier(n)
        gen_tbl.insert(0, "year", year)
        generation_parts.append(gen_tbl)
        _concat_write(generation_parts, out_dir / "generation_by_year.csv")

        charge_tbl = storage_charge_by_carrier(n)
        charge_tbl.insert(0, "year", year)
        charge_parts.append(charge_tbl)
        _concat_write(charge_parts, out_dir / "storage_charge_by_year.csv")

        lmp = lmp_by_bus(n)
        lmp.insert(0, "year", year)
        lmp_parts.append(lmp)
        _concat_write(lmp_parts, out_dir / "lmp_by_year.csv")
        print("Zonal shadow prices, mean over snapshots ($/MWh):", flush=True)
        print(n.buses_t.marginal_price.mean().to_string(), flush=True)

        prm_row = None
        if reserve_margin:
            prm_row = print_reserve_margin_table(
                n, year, aggregate_large_cc=aggregate_large_cc,
            )
            prm_parts.append(pd.DataFrame([prm_row]))
            _concat_write(prm_parts, out_dir / "reserve_margin_by_year.csv")
        if zonal_ra:
            zonal_tbl = print_zonal_ra_table(
                n, year, aggregate_large_cc=aggregate_large_cc,
            )
            zonal_parts.append(zonal_tbl)
            _concat_write(zonal_parts, out_dir / "zonal_ra_by_year.csv")
        co2_row = None
        if co2_cap:
            co2_row = print_co2_table(
                n, year, aggregate_large_cc=aggregate_large_cc, co2_path=co2_path,
            )
            co2_parts.append(pd.DataFrame([co2_row]))
            _concat_write(co2_parts, out_dir / "co2_by_year.csv")
        print("Storage cyclic-week energy balance (expect ~0):", flush=True)
        print_soc_check(n, periods)
        interchange = print_net_interchange(n)
        net_twh = float("nan")
        if len(interchange):
            interchange.insert(0, "year", year)
            interchange_parts.append(interchange)
            _concat_write(interchange_parts, out_dir / "interchange_by_year.csv")
            total_rows = interchange[interchange["interface"] == "total"]
            if len(total_rows):
                net_twh = float(total_rows["twh"].iloc[0])

        gross_interchange = gross_interchange_by_market(n)
        if len(gross_interchange):
            gross_interchange.insert(0, "year", year)
            gross_interchange_parts.append(gross_interchange)
            _concat_write(gross_interchange_parts, out_dir / "gross_interchange_by_year.csv")

        summary = {
            "year": year,
            "status": status,
            "condition": condition,
            "wall_s": elapsed,
            "objective": float(n.objective),
        }
        if prm_row is not None:
            summary["prm_slack_mw"] = prm_row["slack_mw"]
            summary["prm_dual"] = prm_row["dual"]
        if co2_row is not None:
            summary["co2_solved_mmt"] = co2_row["solved_mmt"]
            summary["co2_cap_mmt"] = co2_row["cap_mmt"]
            summary["co2_dual"] = co2_row["dual"]
        if pd.notna(net_twh):
            summary["net_interchange_twh"] = net_twh
        summary_parts.append(pd.DataFrame([summary]))
        _concat_write(summary_parts, out_dir / "summary_by_year.csv")

        cost_row, _mismatches = write_year_cost_dispatch(
            n, year, periods, out_dir, generation=gen_tbl,
        )
        cost_parts.append(pd.DataFrame([_cost_csv_row(cost_row)]))
        _concat_write(cost_parts, out_dir / "cost_by_year.csv")
        _write_npv_if_complete(pd.concat(cost_parts, ignore_index=True), out_dir)

        capacity_rows.extend(capacity_records(n, year))
        pd.DataFrame(capacity_rows).to_csv(csv_path, index=False)

        out_path = run_checkpoint_path(network_prefix, year)
        n.export_to_netcdf(out_path)
        print(f"  wrote {out_path.relative_to(PROJECT_ROOT)}", flush=True)

    print("\n=== MYOPIC SEQUENCE COMPLETE ===", flush=True)
    print(f"  {csv_path.relative_to(PROJECT_ROOT)}", flush=True)
    print(f"  {run_solve_log_path(network_prefix).relative_to(PROJECT_ROOT)}", flush=True)
    for year in INVESTMENT_YEARS:
        print(
            f"  {run_checkpoint_path(network_prefix, year).relative_to(PROJECT_ROOT)}",
            flush=True,
        )
