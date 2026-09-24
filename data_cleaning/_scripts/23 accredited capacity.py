"""
Script 23: Accredited Capacity

Builds accredited_capacity_pct on colorado_resources.csv (existing fleet) -- the % of each
resource's MaxCap counted toward planning reserve margin compliance. Model-agnostic by design:
% of nameplate is the standard way capacity credit/ELCC is expressed in the literature (e.g.
NREL Cambium), independent of any target platform's own schema. Translation to a specific
platform's own parameter (e.g. EnCompass's FirmCap) happens only at that platform's own export
step, not here.

This is a multi-step accreditation build-out; ELCC-based treatment for wind/solar/short-duration
storage (both existing and candidate) is a separate, later step, not part of this file yet.

────────────────────────────────────────────────────────────────────────────
Step 1: Existing dispatchable resources (colorado_resources.csv)
────────────────────────────────────────────────────────────────────────────
Dispatchable resources (Coal, Gas:CC/CT/IC/ST, Hydro, Hydro:Pumped -- 75 of 121 resources):
  accredited_capacity_pct = 100 * (1 - FOR/100)
`FOR` (already on colorado_resources.csv, from `17 mincap and outage rates.py`) is actually
EFORd -- Equivalent Demand Forced Outage Rate, NERC GADS 2020-2024 -- chosen there over raw GADS
FOR specifically because EFORd conditions on hours the unit was actually demanded, which is
exactly the right basis for an unforced-capacity-style derate. No new sourcing needed here.

Hydro and Hydro:Pumped are included in this dispatchable tier (2026-08-05 decision): both have
real GADS-sourced EFORd values via the same method as thermal. Their capacity value could in
principle also depend on water-year/seasonal energy budgets, but that's treated as a smaller
future refinement, not a reason to defer them to the ELCC pass with the genuinely
weather/penetration-driven technologies.

Deferred (Solar:PV, Wind, Storage:Battery -- 46 of 121 resources): accredited_capacity_pct is
left blank, not zero or a guessed value -- these need a real ELCC-based treatment (planned
future step, likely sourced from NREL Cambium) since a flat EFORd-style derate would misstate
how little capacity value they retain at higher penetration, which is exactly the outcome this
project is trying to avoid. Their FOR is already 0/not-applicable per Script 17's own
special-casing, consistent with excluding them here.

Output: colorado_resources.csv gains two columns -- accredited_capacity_pct (%, 2dp) and
accredited_capacity_source (string, always populated so a blank accredited_capacity_pct reads
as an intentional deferral, not missing data).

────────────────────────────────────────────────────────────────────────────
Step 2: Candidate dispatchable technologies (candidate_technology_parameters.csv)
────────────────────────────────────────────────────────────────────────────
Covers Gas:CT, Gas:CC, Nuclear:SMR, Geothermal -- the dispatchable quarter of Script 21's
8-technology candidate set. Solar:PV/Wind/Solar+Storage/Storage:Battery stay deferred to the
ELCC pass, same as the existing fleet's equivalents.

Source priority checked 2026-08-05, in the order the user asked for (ATB -> EIA -> GADS):
  - ATB: no generic outage/availability parameter across all 25 `core_metric_parameter` values
    in the raw cached file -- *except* Nuclear - Small, which reports a Capacity Factor of 0.93,
    flat across every year/scenario/case/crpyears. Used directly for Nuclear:SMR (no derate
    formula -- nuclear is baseload/must-run and rarely economically curtailed, so ATB's CF here
    already functions as a realized-availability figure, not a dispatch-driven CF like
    wind/solar/gas; also consistent with the real US nuclear fleet's actual ~92-93% capacity
    factor). Confirmed with the user this is preferable to an external literature search.
  - EIA: checked the "Cost and Performance Characteristics of New Generating Technologies"
    document (the Sargent & Lundy basis already cited for Script 20's Gas:CC cost cross-check)
    directly -- cost/heat-rate/O&M only, no outage data. Nothing usable found.
  - NERC GADS: has real categories for Gas Turbine, Combined Cycle, and Geothermal (checked the
    same cached brochure Script 17 uses for the existing fleet), each with an "All Sizes"
    aggregate row -- used for Gas:CT/Gas:CC/Geothermal. **"All Sizes", not a size-matched bin**:
    candidates don't have a resolved per-unit block size yet (open question in the broader
    workplan), so size-matching the way Script 17 does for the existing fleet isn't possible
    here without fabricating a size assumption. GADS's nuclear categories are all >=400 MW
    (large-LWR fleet) -- a real technology mismatch for SMR, not used.

  accredited_capacity_pct:
    Gas:CT      = 100 * (1 - 9.86/100) = 90.14   (GADS Gas Turbine, All Sizes, EFORd 9.86%)
    Gas:CC      = 100 * (1 - 4.91/100) = 95.09   (GADS Combined Cycle, All Sizes, EFORd 4.91% --
                  matches the existing fleet's Gas:CC value exactly, same GADS row)
    Geothermal  = 100 * (1 - 4.52/100) = 95.48   (GADS Geothermal, All Sizes, EFORd 4.52%)
    Nuclear:SMR = 93.00                          (ATB 2024, Nuclear - Small, Capacity Factor)

Output: candidate_technology_parameters.csv gains the same two columns as the existing-fleet
step -- accredited_capacity_pct (%, 2dp) and accredited_capacity_source.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT     = find_project_root()
DATA_CLEANING    = PROJECT_ROOT / "data_cleaning"
RESOURCES_CSV    = DATA_CLEANING / "resources" / "colorado_resources.csv"
CANDIDATE_PARAMS_CSV = DATA_CLEANING / "resources" / "candidate_technology_parameters.csv"

DISPATCHABLE_TECH_TYPES = [
    "Coal", "Gas:CC", "Gas:CT", "Gas:IC", "Gas:ST", "Hydro", "Hydro:Pumped",
]
DEFERRED_TECH_TYPES = ["Solar:PV", "Wind", "Storage:Battery"]

DISPATCHABLE_SOURCE = "efordd_derate_nerc_gads_2020_2024"
DEFERRED_SOURCE      = "deferred_pending_elcc_wind_solar_storage"

# Candidate dispatchable technologies: NERC GADS "All Sizes" EFORd (%), 2020-2024 brochure --
# see module docstring, Step 2, for the source-priority research (ATB/EIA checked first).
CANDIDATE_GADS_EFORD_ALL_SIZES: dict[str, float] = {
    "Gas:CT":     9.86,   # GADS "Gas Turbine, All Sizes"
    "Gas:CC":     4.91,   # GADS "Combined Cycle, All Sizes"
    "Geothermal": 4.52,   # GADS "Geothermal, All Sizes"
}
CANDIDATE_GADS_SOURCE = "efordd_derate_nerc_gads_2020_2024_all_sizes"

# Nuclear:SMR: ATB 2024 Nuclear - Small Capacity Factor, used directly (not a derate formula --
# see module docstring for why this already represents realized availability for a baseload tech).
NUCLEAR_SMR_ACCREDITED_PCT = 93.0
NUCLEAR_SMR_SOURCE = "atb_2024_nuclear_small_capacity_factor"

CANDIDATE_DEFERRED_TECH_CLASSES = ["Solar:PV", "Wind", "Solar+Storage", "Storage:Battery"]


def build_dispatchable_accreditation(resources: pd.DataFrame) -> pd.DataFrame:
    resources = resources.copy()
    resources["accredited_capacity_pct"]    = pd.NA
    resources["accredited_capacity_source"] = pd.NA

    dispatchable_mask = resources["TechType"].isin(DISPATCHABLE_TECH_TYPES)
    resources.loc[dispatchable_mask, "accredited_capacity_pct"] = (
        (100 * (1 - resources.loc[dispatchable_mask, "FOR"] / 100)).round(2)
    )
    resources.loc[dispatchable_mask, "accredited_capacity_source"] = DISPATCHABLE_SOURCE

    deferred_mask = resources["TechType"].isin(DEFERRED_TECH_TYPES)
    resources.loc[deferred_mask, "accredited_capacity_source"] = DEFERRED_SOURCE

    unclassified = ~(dispatchable_mask | deferred_mask)
    if unclassified.any():
        raise ValueError(
            f"TechType(s) not classified as dispatchable or deferred: "
            f"{resources.loc[unclassified, 'TechType'].unique().tolist()}"
        )

    return resources


def build_candidate_dispatchable_accreditation(candidate_params: pd.DataFrame) -> pd.DataFrame:
    candidate_params = candidate_params.copy()
    candidate_params["accredited_capacity_pct"]    = pd.NA
    candidate_params["accredited_capacity_source"] = pd.NA

    gads_mask = candidate_params["tech_class"].isin(CANDIDATE_GADS_EFORD_ALL_SIZES)
    eford = candidate_params.loc[gads_mask, "tech_class"].map(CANDIDATE_GADS_EFORD_ALL_SIZES)
    candidate_params.loc[gads_mask, "accredited_capacity_pct"] = (100 * (1 - eford / 100)).round(2)
    candidate_params.loc[gads_mask, "accredited_capacity_source"] = CANDIDATE_GADS_SOURCE

    smr_mask = candidate_params["tech_class"] == "Nuclear:SMR"
    candidate_params.loc[smr_mask, "accredited_capacity_pct"]    = NUCLEAR_SMR_ACCREDITED_PCT
    candidate_params.loc[smr_mask, "accredited_capacity_source"] = NUCLEAR_SMR_SOURCE

    deferred_mask = candidate_params["tech_class"].isin(CANDIDATE_DEFERRED_TECH_CLASSES)
    candidate_params.loc[deferred_mask, "accredited_capacity_source"] = DEFERRED_SOURCE

    unclassified = ~(gads_mask | smr_mask | deferred_mask)
    if unclassified.any():
        raise ValueError(
            f"tech_class value(s) not classified: "
            f"{candidate_params.loc[unclassified, 'tech_class'].unique().tolist()}"
        )

    return candidate_params


def print_candidate_summary(candidate_params: pd.DataFrame) -> None:
    computed = candidate_params[candidate_params["accredited_capacity_pct"].notna()]
    deferred = candidate_params[candidate_params["accredited_capacity_pct"].isna()]

    print(f"\n  Candidate dispatchable technologies ({len(computed)} of {len(candidate_params)}):")
    print(f"  {'tech_class':<14} {'accredited %':>13}  source")
    print(f"  {'-'*70}")
    for _, r in computed.iterrows():
        print(f"  {r['tech_class']:<14} {r['accredited_capacity_pct']:>13.2f}  {r['accredited_capacity_source']}")

    print(f"\n  Deferred candidate technologies ({len(deferred)} of {len(candidate_params)}), pending ELCC:")
    print(deferred["tech_class"].to_string(index=False))


def print_summary(resources: pd.DataFrame) -> None:
    dispatchable = resources[resources["TechType"].isin(DISPATCHABLE_TECH_TYPES)]
    deferred     = resources[resources["TechType"].isin(DEFERRED_TECH_TYPES)]

    print(f"\n  Dispatchable resources ({len(dispatchable)} of {len(resources)}):")
    print(f"  {'TechType':<16} {'count':>6} {'mean %':>8} {'min %':>8} {'max %':>8}")
    print(f"  {'-'*50}")
    for tech_type in DISPATCHABLE_TECH_TYPES:
        sub = dispatchable[dispatchable["TechType"] == tech_type]["accredited_capacity_pct"]
        if sub.empty:
            continue
        print(f"  {tech_type:<16} {len(sub):>6} {sub.mean():>8.2f} {sub.min():>8.2f} {sub.max():>8.2f}")

    print(f"\n  Deferred resources ({len(deferred)} of {len(resources)}), pending ELCC:")
    print(deferred["TechType"].value_counts().to_string())
    still_blank = deferred["accredited_capacity_pct"].isna().all()
    print(f"  accredited_capacity_pct blank for all deferred rows: {'OK' if still_blank else 'MISMATCH'}")


def main() -> None:
    print("\n--- Script 23: Accredited Capacity ---")

    print("\n=== Step 1: Existing dispatchable resources ===")
    print("\n[1/3] Loading colorado_resources.csv...")
    resources = pd.read_csv(RESOURCES_CSV)

    print("\n[2/3] Computing dispatchable accreditation (EFORd derate)...")
    resources = build_dispatchable_accreditation(resources)

    print("\n[3/3] Saving output...")
    resources.to_csv(RESOURCES_CSV, index=False)
    print(f"  Updated: {RESOURCES_CSV.name}  ({len(resources)} rows)")

    print_summary(resources)

    print("\n=== Step 2: Candidate dispatchable technologies ===")
    print("\n[1/3] Loading candidate_technology_parameters.csv...")
    candidate_params = pd.read_csv(CANDIDATE_PARAMS_CSV)

    print("\n[2/3] Computing candidate dispatchable accreditation...")
    candidate_params = build_candidate_dispatchable_accreditation(candidate_params)

    print("\n[3/3] Saving output...")
    candidate_params.to_csv(CANDIDATE_PARAMS_CSV, index=False)
    print(f"  Updated: {CANDIDATE_PARAMS_CSV.name}  ({len(candidate_params)} rows)")

    print_candidate_summary(candidate_params)


if __name__ == "__main__":
    main()
