"""
Script 21: Candidate Technology Parameters

Builds candidate_technology_parameters.csv -- one row per candidate tech_class, holding the
static/technology-level performance parameters (emissions, minimum stable operating level,
storage duration/efficiency) that PyPSA needs alongside the time-varying cost/financing
trajectory already in atb_candidate_lookup.csv (Script 20). Kept as a separate file, joined by
tech_class at the future PyPSA-network-build step -- same separation of concerns as the existing
fleet's colorado_resources.csv (static attributes) vs. atb_om_lookup.csv (technology lookup).

Reuses methodology already built and cited for the *existing* fleet wherever a technology-class
precedent exists (Scripts 15, 17, 18), rather than sourcing anything new for those cases.
Colorado has no existing SMR or Geothermal resource to derive a technology-class average
minimum stable level from (the approach used for Gas:CT/CC); see the Minimum stable operating
level section below for how each is instead sourced/assumed. Ramp rates are out of scope for
this file entirely -- confirmed (via repo-wide grep) that this parameter doesn't exist anywhere
in the pipeline yet, for the existing fleet either, and isn't needed for a first PyPSA pass.

Emissions (CO2/NOx/SO2, lb/MWh) -- reuses Script 15's ZERO_EMISSION_TECHS / PROXY_DEFAULTS
pattern (data_cleaning/_scripts/15 heat rates and emissions.py):
  - Zero for Solar:PV, Wind, Solar+Storage, Storage:Battery, Nuclear:SMR, Geothermal (no direct
    combustion -- same logic already applied to Wind/Solar/Hydro/Storage, extended here to SMR
    and next-gen enhanced geothermal, which are likewise non-combustion).
  - Gas:CT / Gas:CC: CO2 is recomputed from our own candidate-specific ATB heat rate rather than
    copied from Script 15's existing-fleet proxy -- co2_lb_per_mwh = 117 x heat_rate_mmbtu_per_mwh
    (117 lb CO2/MMBtu, EPA "Emission Factors for GHG Inventories" 2024 -- the same source Script
    15 cites; this reproduces Script 15's own existing-fleet numbers when applied to *its* heat
    rate assumption: 117 x 7.6 = 890 for CC, 117 x 10.8 = 1260 for CT). Using our own new-build
    heat rate is more accurate here, since a new 2-on-1 F-Frame CC is more efficient than the
    existing fleet's older-vintage average. Heat rate is read at 2030 (Gas:CT is flat across the
    whole 2022-2050 trajectory; Gas:CC drifts only ~3%, so a single representative year is a
    reasonable simplification for this technology-level table).
    NOx/SO2 aren't heat-rate-derived the same way (they're measured CO fleet averages via CEMS),
    so these reuse Script 15's existing Gas:CT (0.5 / 0.03 lb/MWh) and Gas:CC (0.3 / 0.02 lb/MWh)
    proxy values directly as the best available stand-in absent a better new-build-specific source.

Minimum stable operating level -- only meaningful for thermal dispatchable technologies; PyPSA's
natural p_min_pu=0 default covers Solar/Wind/Storage/Hybrid without needing a value (mirrors how
Script 17 only computes a real Pmin fraction for thermal techs):
  - Gas:CT / Gas:CC: modeled directly at the manufacturer-published turndown spec (2026-08-16
    decision), not a fleet-capacity-weighted average -- see below for how this changed.
    Originally (2026-08-03) computed as a capacity-weighted Pmin fraction from
    colorado_resources.csv (sum(MinCap) / sum(MaxCap) by TechType, same formula as Script 17's own
    technology-class fallback), then cross-checked against published new-build manufacturer specs
    on the theory that the existing CO fleet's older-vintage units could plausibly be less
    flexible than a new-build candidate:
      - Gas:CC (14.4% derived at the time) vs. GE 7HA.01/.02/.03 fact sheet (GEA32928B, 2021),
        2x1 combined-cycle configuration (matching this script's ATB config choice, not the 1x1
        config's 33.0%): "Plant Turndown - Minimum Load (%) = 15.0%" -- fact sheet filed as an
        exhibit in Kentucky PSC Case No. 2022-00402; re-confirmed directly against GE's own
        published fact sheet, independent of the docstring citation, 2026-08-16.
      - Gas:CT (25.7% derived at the time) vs. Siemens Energy SGT6-5000F (F-class, matching our
        ATB configuration choice) product page: "turndown in emissions compliance to 30% load",
        with single-digit NOx/CO maintained down to that point -- re-confirmed directly against
        Siemens Energy's own current product page, independent of the docstring citation,
        2026-08-16.
    At the time (2026-08-03), the derived and manufacturer figures were close enough ("essentially
    identical"/"same range") that the derived value was kept, with the manufacturer specs recorded
    only as corroboration. That changed 2026-08-14, when colorado_resources.csv's MinCap was fixed
    from a per-unit to a resource-total convention (see resource_planning_workplan.md) -- Script 21
    wasn't rerun at the time, so this went unnoticed until 2026-08-16, when rerunning it for an
    unrelated change (candidate lifetime) recomputed the derived fractions much higher: Gas:CC
    14.4%->30.25%, Gas:CT 25.7%->38.21%, the latter now exceeding the Siemens spec outright.
    Decision (2026-08-16): rather than treat the corrected fleet average as the new modeled value,
    use the manufacturer specs directly (Gas:CT=30.0%, Gas:CC=15.0%) -- consistent with, not a
    reversal of, this section's original reasoning: a new-build candidate plant is expected to be
    at least as flexible as, and plausibly more flexible than, the aging existing CO fleet a
    capacity-weighted average is computed over. The fleet-derived figures are kept here only as
    historical context for how the manufacturer specs were first identified as the relevant
    comparison.
  - Nuclear:SMR: 20% (2026-08-04 decision). Sourced from Chang, C.-K.; Oyando, H.C. "Review of
    the Requirements for Load Following of Small Modular Reactors." Energies 2022, 15, 6327.
    https://doi.org/10.3390/en15176327 -- Table 4 (European Utilities Requirements for new
    light-water reactors) states an optional extended operating range down to 20% of rated
    power, and the paper's body text separately describes ~20% as the commonly-cited practical
    minimum for conventional plants generally. Caveat verified directly (not assumed): ATB's
    "Nuclear - Small" cost basis (Abou-Jaoude et al. 2024, INL meta-analysis) is a blended
    average across multiple advanced reactor concepts, not exclusively light-water-reactor
    designs -- so this is an approximation, not an exact technology match, accepted as
    reasonable given LWR-based SMRs (e.g. NuScale) are the most mature, licensed subset of the
    category.
  - Geothermal: 20% (2026-08-04 decision) -- an explicit proxy, not an independently sourced
    value. No engineering-validated minimum-load source was found for geothermal specifically
    despite an extensive search (ATB, EIA AEO, DOE GeoVision, Fervo public materials, ORMAT
    specs all checked, none had one). Ricks et al. 2025 (Nature Energy, "The role of flexible
    geothermal power in decarnonized electricity systems") models full curtailment to zero as
    its default case, but that is a systems-economics upper-bound value exploration, not an
    engineering-validated operating assumption -- the paper itself flags unmitigated curtailment
    as a possible well-integrity risk without resolving it. Rather than assert either extreme
    (0% or fully baseload) without support, 20% borrows the SMR assumption above as a rough
    placeholder pending a better geothermal-specific source.

Storage parameters -- only for Storage:Battery (and the hybrid's battery half, same technology):
reuses Script 18's already-cited values directly (data_cleaning/_scripts/18 storage parameters.py):
  - round_trip_efficiency_pct = 85% (AC-AC, NREL ATB 2024 Utility-Scale Battery Storage
    documentation -- exact figure Script 18 already uses for the existing fleet).
  - storage_duration_hours = 4 -- already implicit in Script 20's ATB techdetail choice
    ("4Hr Battery Storage"), surfaced here as its own column.
  - Not applicable (blank) for all other technologies.

Zone siting (allowed_zones) -- added 2026-08-11. First, deliberately minimal pass at candidate
siting: user decided to run the initial PyPSA model with unlimited build for every candidate
tech in every zone EXCEPT Wind, which is restricted to East/North/South. This is not a new
constraint invented here -- it matches Script 7's existing scope decision ("Wind is only modeled
for East, North, and South zones; Denver, Mountain, and West are skipped for the initial wind
deployment"), so this column makes that existing data reality explicit in the platform-neutral
table rather than leaving it as an undocumented side effect of which CF shapes happen to exist.
MW-level resource potential / supply curves (i.e. real capacity limits per zone, not just an
allowed/disallowed flag) are deliberately deferred to a later pass, once initial model behavior
suggests where refinement is actually needed -- see [[project_resource_planning_workplan]].
`allowed_zones` = "All" (any of the 6 CO zones) or a comma-separated subset; consuming code
(future PyPSA/EnCompass network-build step) should treat "All" as no restriction rather than
literally enumerating all 6 zone names, so this stays correct automatically if the zone set ever
changes.

Operating lifetime (lifetime_years) -- added 2026-08-16. Reuses Script 19's already-cited
ATB_TECH_LIFE values directly (data_cleaning/_scripts/19 useful life and retirement dates.py),
which that script's own docstring already earmarked for exactly this reuse ("doubles as the
reference table for Phase 3 candidate-resource OpLife assumptions"), rather than sourcing a new
assumption. Two of the eight tech_classes need a key rename between the two scripts' naming
conventions (`Nuclear:SMR` here vs. Script 19's `Nuclear`; `Solar+Storage` here vs. Script 19's
`Utility-Scale PV-Plus-Battery`) -- the other six tech_classes already share identical names.
Values: Solar:PV/Wind/Solar+Storage/Geothermal = 30yr (ATB 2024 Tech Life CRP), Storage:Battery =
15yr (ATB 2024 Tech Life CRP -- notably shorter than its 30yr `crpyears` financing/cost-recovery
period in atb_candidate_lookup.csv; those are intentionally distinct concepts, see Script 20's own
docstring), Gas:CT/Gas:CC = 30yr (EIA AEO2026's 30-year cost-recovery convention, not ATB -- see
Script 19 for the citation), Nuclear:SMR = 60yr (ATB 2024 Tech Life CRP; no distinct SMR figure
exists in ATB, same as Nuclear-Large).

Output: candidate_technology_parameters.csv -- one row per tech_class (8 rows), matching Script
20's TECH_SPEC keys exactly so the two files join cleanly.
"""

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT  = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"

CANDIDATE_LOOKUP  = DATA_CLEANING / "resources" / "costs" / "atb" / "atb_candidate_lookup.csv"
OUT_CSV           = DATA_CLEANING / "resources" / "candidate_technology_parameters.csv"

HEAT_RATE_YEAR = 2030   # representative year for Gas:CT/CC CO2 calc (see module docstring)

# All 8 candidate tech_classes, matching Script 20's TECH_SPEC keys exactly.
TECH_CLASSES = [
    "Solar:PV", "Wind", "Solar+Storage", "Storage:Battery",
    "Gas:CT", "Gas:CC", "Nuclear:SMR", "Geothermal",
]

ZERO_EMISSION_TECHS = {
    "Solar:PV", "Wind", "Solar+Storage", "Storage:Battery", "Nuclear:SMR", "Geothermal",
}

# Script 15's existing-fleet NOx/SO2 proxy values (lb/MWh) -- not heat-rate-derived, so reused
# as-is; CO2 is recomputed below from our own candidate-specific ATB heat rate instead.
EPA_CO2_LB_PER_MMBTU = 117.0
GAS_NOX_SO2_PROXY: dict[str, dict] = {
    "Gas:CT": {"nox": 0.5, "so2": 0.03},
    "Gas:CC": {"nox": 0.3, "so2": 0.02},
}

# Script 18's already-cited battery storage parameters (existing fleet), reused for candidates.
BATTERY_ROUND_TRIP_EFF_PCT = 85.0
BATTERY_DURATION_HOURS     = 4.0
STORAGE_TECHS = {"Storage:Battery", "Solar+Storage"}

# Zone siting -- see module docstring "Zone siting (allowed_zones)" section. "All" = no
# restriction (any of the 6 CO zones); Wind is the only tech restricted for now, matching
# Script 7's existing East/North/South-only wind CF shape coverage.
WIND_ALLOWED_ZONES = "East,North,South"

# Operating lifetime (yr) -- see module docstring "Operating lifetime" section. Copied from
# Script 19's ATB_TECH_LIFE (19 useful life and retirement dates.py), with key renames for the
# two tech_classes that don't share a name across the two scripts (Nuclear:SMR<->Nuclear,
# Solar+Storage<->Utility-Scale PV-Plus-Battery).
CANDIDATE_TECH_LIFE: dict[str, tuple[float, str]] = {
    "Solar:PV":        (30.0, "atb_2024_tech_life"),
    "Wind":            (30.0, "atb_2024_tech_life"),
    "Solar+Storage":   (30.0, "atb_2024_tech_life"),
    "Storage:Battery": (15.0, "atb_2024_tech_life"),
    "Gas:CT":          (30.0, "eia_aeo2026_30yr_cost_recovery"),
    "Gas:CC":          (30.0, "eia_aeo2026_30yr_cost_recovery"),
    "Nuclear:SMR":     (60.0, "atb_2024_tech_life"),
    "Geothermal":      (30.0, "atb_2024_tech_life"),
}

# Columns this script owns/computes itself (everything build_parameters() produces besides the
# tech_class join key). Downstream scripts (22 Fuel, 23/24 accredited capacity) append their own
# columns onto this same file via their own read-modify-write -- see preserve_downstream_columns().
OWNED_COLUMNS = [
    "min_stable_pct", "mincap_source", "co2_lb_per_mwh", "nox_lb_per_mwh", "so2_lb_per_mwh",
    "emission_source", "storage_duration_hours", "round_trip_efficiency_pct", "storage_source",
    "allowed_zones", "lifetime_years", "lifetime_source",
]

# Fixed minimum stable operating level assumptions (see module docstring for full citation/
# confidence detail on each). Nuclear:SMR is sourced from a real (if imperfectly matched)
# reference; Geothermal is an explicit proxy borrowed from the SMR value, not independently
# sourced -- both decided 2026-08-04. Gas:CT/Gas:CC use published manufacturer turndown specs
# directly (2026-08-16 decision, superseding an earlier fleet-capacity-weighted-derived value --
# see docstring for why).
FIXED_MIN_STABLE_PCT: dict[str, float] = {
    "Nuclear:SMR": 20.0,
    "Geothermal":  20.0,
    "Gas:CT":      30.0,
    "Gas:CC":      15.0,
}
FIXED_MINCAP_SOURCE: dict[str, str] = {
    "Nuclear:SMR": "chang_oyando_2022_energies_eur_new_lwr_optional_min_20pct",
    "Geothermal":  "proxy_borrowed_from_nuclear_smr_assumption__no_geothermal_specific_source_found",
    "Gas:CT":      "siemens_sgt6_5000f_manufacturer_turndown_30pct",
    "Gas:CC":      "ge_7ha_2x1_cc_manufacturer_turndown_15pct",
}


def build_parameters(candidate_lookup: pd.DataFrame) -> pd.DataFrame:
    heat_rates = (
        candidate_lookup[candidate_lookup["atb_year"] == HEAT_RATE_YEAR]
        .set_index("tech_class")["heat_rate_mmbtu_per_mwh"]
    )

    rows = []
    for tech_class in TECH_CLASSES:
        row = {
            "tech_class":                tech_class,
            "min_stable_pct":            None,
            "mincap_source":             None,
            "co2_lb_per_mwh":            0.0,
            "nox_lb_per_mwh":            0.0,
            "so2_lb_per_mwh":            0.0,
            "emission_source":           "zero_emission",
            "storage_duration_hours":    None,
            "round_trip_efficiency_pct": None,
            "storage_source":            None,
            "allowed_zones":             "All",
            "lifetime_years":            None,
            "lifetime_source":           None,
        }

        if tech_class == "Wind":
            row["allowed_zones"] = WIND_ALLOWED_ZONES

        row["lifetime_years"], row["lifetime_source"] = CANDIDATE_TECH_LIFE[tech_class]

        if tech_class not in ZERO_EMISSION_TECHS:
            heat_rate = float(heat_rates.loc[tech_class])
            row["co2_lb_per_mwh"]  = round(EPA_CO2_LB_PER_MMBTU * heat_rate, 1)
            row["nox_lb_per_mwh"]  = GAS_NOX_SO2_PROXY[tech_class]["nox"]
            row["so2_lb_per_mwh"]  = GAS_NOX_SO2_PROXY[tech_class]["so2"]
            row["emission_source"] = "epa_ghg_factor_x_atb_heat_rate_co2__script15_proxy_noxso2"

        if tech_class in FIXED_MIN_STABLE_PCT:
            row["min_stable_pct"] = FIXED_MIN_STABLE_PCT[tech_class]
            row["mincap_source"]  = FIXED_MINCAP_SOURCE[tech_class]

        if tech_class in STORAGE_TECHS:
            row["storage_duration_hours"]    = BATTERY_DURATION_HOURS
            row["round_trip_efficiency_pct"] = BATTERY_ROUND_TRIP_EFF_PCT
            row["storage_source"]            = "atb_2024_battery_storage_documentation"

        rows.append(row)

    return pd.DataFrame(rows)


def print_summary(params: pd.DataFrame) -> None:
    print(f"\n  Candidate technology parameters ({len(params)} rows):")
    print(
        f"  {'tech_class':<16} {'MinStable%':>10} {'CO2':>8} {'NOx':>6} {'SO2':>6}  "
        f"{'Dur(hr)':>7} {'RTE%':>5}  {'Life(yr)':>8}"
    )
    print(f"  {'-'*80}")
    for _, r in params.iterrows():
        ms   = f"{r['min_stable_pct']:>10.2f}" if pd.notna(r["min_stable_pct"]) else f"{'--':>10}"
        dur  = f"{r['storage_duration_hours']:>7.0f}" if pd.notna(r["storage_duration_hours"]) else f"{'--':>7}"
        rte  = f"{r['round_trip_efficiency_pct']:>5.0f}" if pd.notna(r["round_trip_efficiency_pct"]) else f"{'--':>5}"
        life = f"{r['lifetime_years']:>8.0f}" if pd.notna(r["lifetime_years"]) else f"{'--':>8}"
        print(
            f"  {r['tech_class']:<16} {ms} {r['co2_lb_per_mwh']:>8.1f} "
            f"{r['nox_lb_per_mwh']:>6.2f} {r['so2_lb_per_mwh']:>6.2f}  {dur} {rte}  {life}"
        )

    print(f"\n  Cross-check vs. Script 15's existing-fleet proxy (117 lb/MMBtu x existing heat rate):")
    print(f"  Gas:CC existing-fleet proxy: 890 lb/MWh (117 x 7.6 MMBtu/MWh)")
    print(f"  Gas:CT existing-fleet proxy: 1,260 lb/MWh (117 x 10.8 MMBtu/MWh)")
    print(f"  (candidate values above use our own new-build ATB heat rate instead -- expected to differ)")


def preserve_downstream_columns(params: pd.DataFrame) -> pd.DataFrame:
    """If OUT_CSV already exists, carry forward any columns this script doesn't own (e.g.
    Fuel from Script 22, accredited_capacity_pct/accredited_capacity_source from Scripts 23/24)
    by joining them back in on tech_class. Without this, rebuilding params from scratch here
    would silently wipe whatever downstream scripts had already appended -- exactly what happened
    2026-08-11 when this script was rerun after Scripts 22-24 had already run, requiring all
    three to be rerun to restore the lost columns. This makes rerunning Script 21 alone safe
    regardless of what a downstream script adds in the future, without this script needing to
    know those columns' names in advance."""
    if not OUT_CSV.exists():
        return params
    existing = pd.read_csv(OUT_CSV)
    downstream_cols = [c for c in existing.columns if c not in OWNED_COLUMNS and c != "tech_class"]
    if not downstream_cols:
        return params
    print(f"  Preserving downstream columns from existing file: {downstream_cols}")
    return params.merge(existing[["tech_class"] + downstream_cols], on="tech_class", how="left")


def main() -> None:
    print("\n--- Script 21: Candidate Technology Parameters ---")

    print("\n[1/3] Loading atb_candidate_lookup.csv...")
    candidate_lookup = pd.read_csv(CANDIDATE_LOOKUP)

    print("\n[2/3] Building candidate technology parameters...")
    params = build_parameters(candidate_lookup)
    params = preserve_downstream_columns(params)

    print("\n[3/3] Saving output...")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    params.to_csv(OUT_CSV, index=False)
    print(f"  Saved: {OUT_CSV.relative_to(PROJECT_ROOT)}  ({len(params)} rows)")

    print_summary(params)


if __name__ == "__main__":
    main()
