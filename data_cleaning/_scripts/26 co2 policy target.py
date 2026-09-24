"""
Script 26: Colorado Electric-Sector CO2 Policy Target

Builds co2_target.csv -- a year-indexed CO2 reduction target (% below a 2005 baseline) for
Colorado's electric sector, plus the 2005 baseline emissions level itself. This is the last
platform-agnostic data-gathering item before the PyPSA build (Transmission/Script 25 and
Accredited Capacity/Scripts 23-24 completed earlier); everything after this is model-build work.

Legal basis (researched 2026-08-11, primary sources read directly, not summarized secondhand):
Colorado's electric-sector CO2 target is real, codified law, corroborated by THREE separate
statutes rather than one:
  - **SB19-236 (2019)** established the original Clean Energy Plan (CEP) framework: "qualifying
    retail utilities" (Xcel Energy/PSCo -- the dominant utility in this model's PSCo zones --
    plus any utility that opts in) must achieve >=80% CO2 reduction from 2005 levels by 2030 via
    a PUC-approved CEP. For 2050 and beyond, the statute uses "goal...so long as doing so is
    technically and economically feasible" language for 100% clean energy resources -- softer
    than the hard 2030 mandate. Xcel's own approved CEP (PUC docket 21A-0141E, approved July
    2022) targets 85%, exceeding the statutory floor.
  - **HB21-1266 (2021)** and **SB23-198** subsequently amended the same CEP process and codified
    the numbers directly into statute: "requires certain electric utilities to reduce emissions
    caused by their retail sales of electricity to customers within Colorado 80% by 2030 relative
    to 2005 levels. It also encourages the utilities to reduce these same emissions by 48% by
    2025." (quoted directly from CDPHE's own 2023 Inventory, Section 2.8.1.2 -- see baseline
    sourcing below). This corroborates SB19-236's number rather than introducing a different one.
  - As of Feb 2024 CEP filings, utilities in aggregate PROJECT exceeding the floor: "approximately
    an 86% reduction in GHG emissions from retail sales by 2030 compared to 2005 levels."

**Deliberately NOT used: HB19-1261.** That's a *separate, economy-wide* law (all sectors, all
GHGs) with lower targets -- 26% by 2025, 50% by 2030, 90% by 2050 vs. 2005 -- confirmed via direct
web research 2026-08-11. Using it here would understate the real, more-aggressive electric-sector-
specific requirement above.

**Deliberately NOT used: the Polis administration's "100% renewable energy by 2040" roadmap.**
Confirmed via direct research this is an administration policy goal/campaign priority (Governor
Polis's own "Roadmap to 100% Renewable Energy by 2040"), not the codified statutory target, which
uses 2050, not 2040.

**Scope simplification (user decision, 2026-08-11): a single statewide target, not
utility/BA-differentiated.** SB19-236/HB21-1266 legally bind "qualifying retail utilities" (Xcel
primarily) -- rural co-ops, dominant in this model's WACM zones (East/West, largely Tri-State
territory), are legally subject to a much weaker ~20% renewable-standard requirement instead, not
this 80%/2030 CO2 target. Applying one statewide target uniformly is a deliberate first-pass
simplification (same pattern already used for wind zone-siting in Script 21's allowed_zones), not
an oversight -- worth revisiting if the PyPSA build later wants BA-level granularity.

**2050 treatment (user decision, 2026-08-11): modeled as a hard constraint anyway**, despite the
statute's softer "goal...if feasible" language for 2050 specifically (vs. 2030's hard mandate).
Worth noting for context: even CDPHE's own most-aggressive modeled policy scenario (NTA, see
baseline sourcing below) does not project literal zero electric-sector emissions by 2050 (2.4 MMT
CO2eq remaining under NTA, vs. 7.8 under RBS and 13.3 under BAU) -- so a hard 100% constraint in
this model is a genuine feasibility test against the state's own scenario planning, not a foregone
conclusion. This is intentional: capacity-expansion modeling is exactly the right tool to explore
that feasibility question, but the softer legal status of the 2050 figure should not be silently
overstated as equivalent to the 2030 mandate.

2005 baseline emissions -- sourced with the same primary-source rigor as Script 25's citations
(documents read directly via pypdf, not trusted from a web-search summary; one such summary
attempt for this exact figure produced an internally-inconsistent number during initial research
and was discarded):
  - **Primary source (used): CDPHE's "2025 Colorado Statewide Inventory of Greenhouse Gas
    Emissions and Sinks," Chapter 3: Energy, July 2026.** Locally saved at
    `data_cleaning/policy/7_8_2026_2025 COGHGI Ch 3 Energy.pdf` (user-downloaded directly from
    CDPHE's own document portal, cdphe.colorado.gov/apcd/greenhouse-gas-inventory ->
    "2023 Greenhouse Gas Inventory Report" link -> oitco.hylandcloud.com document viewer; that
    portal is JS-session-gated and can't be scripted/curled, so a real browser session was
    needed). This is the newest available edition -- supersedes the 2023 Inventory ("Updated
    Final Release," November 2024) originally used in this script's first draft, which gave a
    2005 baseline of 41.8 MMT CO2e (a small, expected upward revision between biennial inventory
    cycles, not an error -- see below).
  - **Table 3.1** ("Energy Sector Emissions by Subsector," PDF p.18/report p.3-5) gives 2005
    Electric Power = **42.204 Tg CO2eq** (Tg = teragrams = MMT). Independently corroborated by
    hand: the report separately states 2023 Electric Power emissions of 28.251 Tg CO2eq (PDF
    p.18) and a "decreased by 13.953 Tg CO2eq (33.1%)" change from 2005 through 2023 (same page)
    -- 28.251 + 13.953 = 42.204, exact agreement with Table 3.1's own value, and 13.953/42.204 =
    33.06% matches the report's own stated 33.1%.
  - **Table 3.3** ("Electric Power Emissions by GHG," PDF p.19/report p.3-18) splits that total
    by gas for 2005: CO2 = **42.023** Tg, CH4 = 0.045 Tg CO2eq, N2O = 0.135 Tg CO2eq (42.023 +
    0.045 + 0.135 = 42.203, rounds to the 42.204 total above). Report text confirms "more than
    99% of Electric Power emissions were CO2 from 2005 through 2023."
  - **This script uses the CO2-ONLY figure (42.023 MMT), not the CO2e total (42.204 MMT)** --
    user decision, 2026-08-11, made explicitly because this project's own per-resource emission
    columns (`co2_RelRateMWh` in colorado_resources.csv, `co2_lb_per_mwh` in
    candidate_technology_parameters.csv, both from Script 15) are pure CO2 only, with no CH4/N2O
    rate columns anywhere in the pipeline. Using a CO2e baseline against a model that only ever
    sums CO2 would bake in a small (~0.43%, 0.181 MMT) but avoidable basis mismatch. Building
    CH4/N2O per-resource rates to properly justify a CO2e comparison was considered and declined
    as unwarranted effort for that small a precision gain -- eGRID does carry CH4/N2O rate
    columns nationally if this is ever revisited (confirmed present in the eGRID2007 file already
    downloaded for the cross-check below), so it's not unreachable, just not built now.
  - **Cross-check (obtained, not used as primary): EPA eGRID2007 Version 1.1, Year 2005 Summary
    Tables** (published December 2008; downloaded directly from epa.gov, read via pypdf).
    Colorado's 2005 state total: 47,420,655.1 short tons CO2 = **43.02 million metric tons CO2**
    (converted at 0.907185 metric tons/short ton). Now an apples-to-apples comparison (both
    pure CO2): 43.02 (eGRID, in-state-generation basis) vs. 42.023 (CDPHE, Electric Power
    subsector, also generation-basis) -- within ~2.3%, reasonable agreement.
  - **Basis caveat, not fully resolved**: CDPHE's Chapter 3 "Electric Power" figure is
    generation-based (in-state power plant emissions), while SB19-236/HB21-1266/SB23-198's legal
    target is retail-sales-based (nets imports/exports/RECs). In the older 2023 Inventory edition,
    these two bases coincided exactly for 2005 (both 41.8). This newer 2025 edition's equivalent
    retail-sales/statutory-tracking table would live in its Chapter 2, which hasn't been obtained
    (only Chapter 3: Energy was available) -- so whether the two bases still coincide in this
    edition is unconfirmed, not assumed.

Target trajectory (user decision, 2026-08-11): **linear interpolation** between milestone years
(2005 = 0% reduction, 2030 = 80%, 2050 = 100%, flat-held at 100% for any later model year),
matching this project's existing interpolation convention (e.g. the ELCC lookup table in
Script 24). No interim legal milestone exists between 2005 and 2030 to interpolate from instead
(the 48%-by-2025 figure above is explicitly "encourages," not a hard target like 2030's 80% --
not used as an interpolation anchor for that reason). Model years before 2030 (this project's
horizon starts at 2026, matching `ba_reserve_margin.csv`) fall on the same straight line back to
the 2005/0% anchor.

Explicitly OUT OF SCOPE for this script (separation-of-concerns, matching
`ba_reserve_margin.csv`/`zone_transfer_limits.csv`'s pattern of gathering raw inputs only, not
wiring them into a platform's constraint mechanism): translating this year-indexed target % and
the 2005 baseline tons into an absolute annual CO2 cap for a PyPSA `global_constraints` (or
EnCompass equivalent) is a future network-build-time step, informed by this data but not built
here.

Output: data_cleaning/policy/co2_target.csv -- one row per model year (2026-2050), columns:
`year`, `co2_reduction_pct_vs_2005` (linear interpolation as described above),
`co2_baseline_2005_mmt_co2` (CO2-only, not CO2e -- see "2005 baseline emissions" above),
`baseline_source`, `target_source`. Also
data_cleaning/policy/co2_target.png -- publication-ready chart matching this project's
established matplotlib convention (Times New Roman, top/right spines removed -- same style
already used for every figure embedded in methods v1.docx, e.g. Scripts 20/22/25).
"""

import os
import sys

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT = find_project_root()
DATA_CLEANING_DIR = PROJECT_ROOT / "data_cleaning"
POLICY_DIR = DATA_CLEANING_DIR / "policy"
OUT_CSV = POLICY_DIR / "co2_target.csv"
OUT_CHART = POLICY_DIR / "co2_target.png"

MODEL_START_YEAR = 2026   # matches ba_reserve_margin.csv's horizon (Script 1)
MODEL_END_YEAR = 2050

# Milestone years and their statutory reduction target (% below 2005), per SB19-236/HB21-1266/
# SB23-198 -- see module docstring "Legal basis" section for full citation and corroboration.
TARGET_MILESTONES_PCT = {
    2005: 0.0,     # baseline year itself, 0% reduction by definition
    2030: 80.0,    # hard statutory mandate
    2050: 100.0,   # statutory "goal...if feasible" language, modeled as hard constraint anyway
                   # per user decision 2026-08-11 -- see docstring "2050 treatment" section
}

# 2005 baseline emissions (MMT CO2, NOT CO2e -- see docstring "2005 baseline emissions" section
# for full sourcing/citation and why CO2-only was chosen over the report's own CO2e total).
BASELINE_CO2_MMT_CDPHE = 42.023
BASELINE_SOURCE_CDPHE = (
    "cdphe_2025_ghg_inventory_ch3_energy_jul2026_table3.3_co2_only_electric_power_subsector"
)

# Cross-check only, not used as the baseline -- see docstring. Pure CO2 (not CO2e),
# in-state-generation basis (not retail-sales), short tons converted to metric tons.
BASELINE_CO2_SHORT_TONS_EGRID = 47_420_655.1
SHORT_TON_TO_METRIC_TON = 0.907185
BASELINE_CO2_MMT_EGRID = round(BASELINE_CO2_SHORT_TONS_EGRID * SHORT_TON_TO_METRIC_TON / 1e6, 2)

TARGET_SOURCE = "sb19-236_hb21-1266_sb23-198_electric_utility_co2_target_linear_interpolation"

PLOT_FONT_SIZE = 24
PLOT_TICK_LABELSIZE = 20


def interpolate_target_pct(year: int) -> float:
    """Linear interpolation between TARGET_MILESTONES_PCT's known years; flat-held before 2005
    (0%, though the model horizon never actually reaches that far back) and after 2050 (100%)."""
    milestone_years = sorted(TARGET_MILESTONES_PCT)
    if year <= milestone_years[0]:
        return TARGET_MILESTONES_PCT[milestone_years[0]]
    if year >= milestone_years[-1]:
        return TARGET_MILESTONES_PCT[milestone_years[-1]]

    for y0, y1 in zip(milestone_years, milestone_years[1:]):
        if y0 <= year <= y1:
            pct0, pct1 = TARGET_MILESTONES_PCT[y0], TARGET_MILESTONES_PCT[y1]
            frac = (year - y0) / (y1 - y0)
            return round(pct0 + frac * (pct1 - pct0), 2)

    raise ValueError(f"year {year} not covered by milestone interpolation")


def build_target_table() -> pd.DataFrame:
    rows = []
    for year in range(MODEL_START_YEAR, MODEL_END_YEAR + 1):
        rows.append({
            "year": year,
            "co2_reduction_pct_vs_2005": interpolate_target_pct(year),
            "co2_baseline_2005_mmt_co2": BASELINE_CO2_MMT_CDPHE,
            "baseline_source": BASELINE_SOURCE_CDPHE,
            "target_source": TARGET_SOURCE,
        })
    return pd.DataFrame(rows)


def plot_target(df: pd.DataFrame, out_path) -> None:
    with plt.rc_context({"font.family": "Times New Roman", "font.size": PLOT_FONT_SIZE}):
        fig, ax = plt.subplots(figsize=(10, 6))

        ax.plot(
            df["year"], df["co2_reduction_pct_vs_2005"],
            linewidth=5, color="#2C7A7B",
        )

        for year, pct in TARGET_MILESTONES_PCT.items():
            if MODEL_START_YEAR <= year <= MODEL_END_YEAR:
                ax.scatter([year], [pct], color="#2C7A7B", s=90, zorder=5)
                ax.annotate(
                    f"{pct:.0f}%", (year, pct),
                    textcoords="offset points", xytext=(0, 12),
                    ha="center", fontsize=PLOT_TICK_LABELSIZE,
                )

        ax.set_xlabel("Year", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("CO2 Reduction vs. 2005 (%)", fontsize=PLOT_FONT_SIZE)
        ax.set_ylim(0, 110)
        ax.tick_params(axis="both", labelsize=PLOT_TICK_LABELSIZE)
        ax.spines[["top", "right"]].set_visible(False)

        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    print(f"  Chart -> {out_path.name}")


def main() -> None:
    print("\n--- Script 26: Colorado Electric-Sector CO2 Policy Target ---")

    print("\n[1/3] Building CO2 target table...")
    target = build_target_table()

    print("\n[2/3] Saving output...")
    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    target.to_csv(OUT_CSV, index=False)
    print(f"  Saved: {OUT_CSV.relative_to(PROJECT_ROOT)} ({len(target)} rows)")

    print("\n[3/3] Saving diagnostic chart...")
    plot_target(target, OUT_CHART)

    print(f"\n  2005 baseline (CDPHE, used): {BASELINE_CO2_MMT_CDPHE} MMT CO2 (CO2-only)")
    print(f"  2005 baseline (eGRID2007, cross-check only): {BASELINE_CO2_MMT_EGRID} MMT CO2 "
          f"({BASELINE_CO2_SHORT_TONS_EGRID:,.1f} short tons)")
    print(f"\nSummary (milestone years):")
    print(target[target["year"].isin([MODEL_START_YEAR, 2030, 2040, 2050])].to_string(index=False))


if __name__ == "__main__":
    main()
