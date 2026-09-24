"""
Script 20: Candidate Technology Cost & Financing Data (NREL ATB 2024)

Extracts full-trajectory (2022-2050) cost, performance, and financing data for the 8
confirmed baseline candidate new-build technologies from NREL ATB 2024, Moderate scenario.
Produces atb_candidate_lookup.csv -- the reference table candidate_resources.csv and
candidate_projects.csv will be built from in a later script. Does NOT build those CSVs itself.

Source: NREL Annual Technology Baseline 2024, `electricity/csv/2024/v3.0.0/ATBe.csv`,
already cached locally (same file as Script 16) at costs/atb/raw/atb_2024.csv.
URL: https://oedi-data-lake.s3.amazonaws.com/ATB/electricity/csv/2024/v3.0.0/ATBe.csv

Scoping decisions (confirmed 2026-07-22 through 2026-07-29 -- see resource_planning_workplan.md
and the candidate-cost-data plan; all verified directly against the raw ATB file, not assumed):

  - Scenario: Moderate. Case: Market (not R&D). Year range: full ATB coverage, 2022-2050.
  - Financing: every candidate is "Unregulated" in EnCompass, but financing fields are pulled
    from ATB regardless -- they seed the Project sheet either way.
  - Resource class: Class5 for Solar/Wind/Hybrid, uniform across zones for this first pass.
    Solar OCC is class-invariant in ATB (identical $1,043.70/kW at every class, 2030) so the
    choice is cost-irrelevant there. Wind Class5 OCC sits in ATB's flat/cheap cost tier
    (Classes 1-6 share $1,228/kW; Classes 7-10 step up to $1,290-$1,640/kW for a larger-rotor
    turbine spec) and its CF (0.460 @ 2030) closely matches this project's own East-zone
    measured wind CF (0.535/0.367/0.455, scripts 9-16, wind_cf_profiles.csv) -- not arbitrary.
  - Gas:CC representative config: NG 2-on-1 Combined Cycle (F-Frame) -- lowest OCC ($1,159.3/kW)
    and Fixed O&M ($31.8/kW-yr) of ATB's three non-CCS/non-fuel-cell CC configs, trading away
    some heat-rate efficiency (6.238 MMBtu/MWh vs 6.040 for the priciest 1-on-1 H-Frame option).
    Cross-checked against EIA AEO2023 "Cost and Performance Characteristics of New Generating
    Technologies" (Sargent & Lundy basis): EIA's multi-shaft CC (1,083 MW) OCC of $1,176/kW is
    within ~1.5% of the ATB figure used here -- independent-methodology agreement. EIA's own
    Rocky-Mountain-region (RMRG) CC costs run below its national figure, so this ATB-based OCC
    sits at/above the CO-region range -- the conservative direction to be wrong in.
  - Gas:CT: single ATB config (NG Combustion Turbine, F-Frame) -- no ambiguity.
  - crpyears (ATB's financing/cost-recovery period -- distinct from EnCompass BookLife/useful
    life, independently set in Script 19's ATB_TECH_LIFE table): 30yr for Solar/Wind/Hybrid/
    Gas/Geothermal/Battery (matches Script 19 wherever ATB offers a matching option), 60yr for
    Nuclear (ATB offers exactly 60). Battery's crpyears choice is numerically inert -- its OCC/
    Fixed O&M are bit-for-bit identical at crpyears=20 vs 30 -- so 30 is used purely so its tag
    matches the Solar financing it borrows (see below), not because it changes any Battery value.
  - Battery has no financing block in ATB at all (no Debt Fraction/Interest Rate/ROE/Tax Rate
    under any techdetail, confirmed) -- borrows Solar:PV's financing trajectory for its Project
    row (`financing_source` column records this).
  - Tax credit case: PTC for Solar/Wind (ATB's only option), ITC for Nuclear/Geothermal (ATB's
    only option), "PTC + ITC" for the PV-Plus-Battery hybrid (PV takes the production credit,
    battery takes standalone ITC -- typical utility PPA structuring; ATB's OCC/Fixed O&M do not
    differ between the hybrid's two tax-credit-case options, only financing fields could).
  - Nuclear/SMR ATB data starts at 2030 -- no fabricated backfill for 2022-2029; consistent with
    SMR not being a realistically buildable candidate before then anyway.
  - Hybrid solar+storage cost split: ATB reports one bundled OCC/Fixed O&M for the whole
    PV-Plus-Battery package. This script computes, per year, the split of that bundle between
    the two paired resources via standalone-cost-ratio weighting:
      hybrid_solar_occ_share = standalone_solar_occ / (standalone_solar_occ + standalone_battery_occ)
    (and the complement for battery). Applying this ratio to actually split the bundled OCC into
    two Resource rows happens in the future CSV-build script, not here.

Output: costs/atb/atb_candidate_lookup.csv -- long format, one row per (tech_class, atb_year),
2022-2050 (Nuclear: 2030-2050 only). Distinct from atb_om_lookup.csv (Script 16's O&M-only,
2024-2035 table for the *existing* fleet).

Both OCC and total CAPEX ($/kW) are extracted (`occ_per_kw`, `capex_per_kw`). OCC is the
recommended figure for EnCompass's CapExRate -- CAPEX = OCC + GCC + capitalized interest during
construction, and EnCompass computes that construction-financing layer itself via CapIntRate/
AFUDC/Construction Profile, so using ATB's CAPEX there would double-count it (verified: +$41/kW
gap for solar, +$3,021/kW for geothermal, 2030 Moderate). CAPEX is kept alongside OCC only
because the modeling approach for candidates isn't fully settled yet -- not a recommendation to
use it instead.

Units kept native to ATB (e.g. Heat Rate stays MMBtu/MWh, not converted to EnCompass's
Btu/kWh) -- unit conversions happen at the future CSV-build step, same pattern Script 16 used
for atb_om_lookup.csv.

CRF gap for Gas:CT/Gas:CC, fixed 2026-08-15 (found while building the PyPSA translation of this
table): ATB publishes CRF directly for every other tech_class here, but not for NaturalGas_FE at
this query -- Debt Fraction/Interest Rate/ROE/Tax Rate/WACC are all present for gas, just not the
pre-computed CRF itself. Rather than leave it blank or borrow another tech's financing (the
existing pattern for Storage:Battery), computed it directly from data already in this table,
using ATB's own documented formula -- not a new approximation:

  1. ATB's CRF formula (verbatim, from the 2024 v3 Workbook's "Financial Definitions" sheet,
     cell C12): CRF = WACC / (1 - (1/(1+WACC))^t), explicitly noted "WACC real" -- i.e. this
     formula wants the inflation-adjusted real WACC, not the nominal WACC this table already
     stores in `wacc_nominal`.
  2. ATB's inflation assumption is documented at exactly 2.5% (same sheet, cell D78: "Assumed
     average inflation rate over project lifetime based on historical data. (2.5% in ReEDS)"),
     confirmed as the literal value 0.025 in the workbook's "WACC Calc" sheet.
  3. Real WACC is the Fisher relation, not the simpler nominal-minus-inflation approximation --
     confirmed by reproducing a worked example already in "WACC Calc" (nominal 6.121309% ->
     real 3.532984%, exact match only via the Fisher form): wacc_real = (1+wacc_nominal)/(1+i) - 1.

  Verified (not just derived) by reproducing ATB's own already-published CRF for three
  technologies this formula was NOT built to fit -- Solar:PV (0.0627), Wind (0.0671), and
  Nuclear:SMR (0.0586, the one 60-year-crpyears case, which showed the largest gap against a
  naive nominal-WACC formula) -- all three matched to the last published digit. `Solar+Storage`
  has the same gap as the two gas techs and gets the same fallback treatment here, though it's
  currently excluded from the PyPSA candidate list for an unrelated reason (hybrid modeling gap,
  see pypsa/Documentation/build_plan.md).

  A naive formula using nominal WACC directly (no inflation adjustment) was tried first and
  rejected -- it overstated ATB's published CRF by ~31-43% across every technology checked,
  confirmed wrong before ever being applied to fill the gas gap.
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

ATB_CACHE = DATA_CLEANING / "resources" / "costs" / "atb" / "raw" / "atb_2024.csv"
ATB_URL   = "https://oedi-data-lake.s3.amazonaws.com/ATB/electricity/csv/2024/v3.0.0/ATBe.csv"
ATB_OUT   = DATA_CLEANING / "resources" / "costs" / "atb" / "atb_candidate_lookup.csv"

ATB_SCENARIO = "moderate"      # ATB CSV uses Title Case; lowercased in load_atb_raw
ATB_CASE     = "Market"        # not "R&D"
ATB_YEARS    = list(range(2022, 2051))   # full candidate-cost trajectory, 2022-2050

# Parameters pulled from ATB for every technology (a tech simply won't have a value for
# parameters it doesn't report -- e.g. no Heat Rate for renewables, no CF for gas/battery).
ATB_PARAMS = [
    "OCC", "CAPEX", "Fixed O&M", "Variable O&M", "Heat Rate", "CF",
    "Debt Fraction", "Interest Rate Nominal", "Rate of Return on Equity Nominal",
    "Tax Rate (Federal and State)", "WACC Nominal", "CRF",
]

# Tech specs: how to extract each candidate technology's cost/performance/financing data.
# Keys:
#   atb_technology     : ATB "technology" column value
#   cost_techdetail     : ATB "techdetail" value for OCC/Fixed O&M/Variable O&M/Heat Rate/CF
#   crpyears            : ATB cost-recovery-period dimension to select (see module docstring)
#   tax_credit_case      : ATB "tax_credit_case" value to select, or None if the tech has no
#                          tax-credit dimension at all (Gas, Battery)
#   has_heat_rate        : whether to pull "Heat Rate" for this tech (thermal only)
#   borrow_financing_from : tech_class to source Debt Fraction/Interest Rate/ROE/Tax Rate/WACC/
#                          CRF from, for technologies with no financing block of their own
TECH_SPEC: dict[str, dict] = {
    "Solar:PV": {
        "atb_technology":  "UtilityPV",
        "cost_techdetail": "Class5",
        "crpyears":        30,
        "tax_credit_case": "PTC",
    },
    "Wind": {
        "atb_technology":  "LandbasedWind",
        "cost_techdetail": "Class5",
        "crpyears":        30,
        "tax_credit_case": "PTC",
    },
    "Solar+Storage": {
        "atb_technology":  "Utility-Scale PV-Plus-Battery",
        "cost_techdetail": "Class5",
        "crpyears":        30,
        "tax_credit_case": "PTC + ITC",
    },
    "Storage:Battery": {
        "atb_technology":  "Utility-Scale Battery Storage",
        "cost_techdetail": "4Hr Battery Storage",
        "crpyears":        30,
        "tax_credit_case": None,
        "borrow_financing_from": "Solar:PV",
    },
    "Gas:CT": {
        "atb_technology":  "NaturalGas_FE",
        "cost_techdetail": "NG Combustion Turbine (F-Frame)",
        "crpyears":        30,
        "tax_credit_case": None,
        "has_heat_rate":   True,
    },
    "Gas:CC": {
        "atb_technology":  "NaturalGas_FE",
        "cost_techdetail": "NG 2-on-1 Combined Cycle (F-Frame)",
        "crpyears":        30,
        "tax_credit_case": None,
        "has_heat_rate":   True,
    },
    "Nuclear:SMR": {
        "atb_technology":  "Nuclear",
        "cost_techdetail": "Nuclear - Small",
        "crpyears":        60,
        "tax_credit_case": "ITC",
        "has_heat_rate":   True,
    },
    "Geothermal": {
        "atb_technology":  "Geothermal",
        "cost_techdetail": "NFEGSBinary",
        "crpyears":        30,
        "tax_credit_case": "ITC",
    },
}

# Spot-check values surfaced during plan review (2030, Moderate) -- printed against script
# output at the end of main() to confirm the filters reproduce the same figures found via
# direct inspection of the raw file.
SPOT_CHECK_2030_OCC: dict[str, float] = {
    "Solar:PV":        1043.70,
    "Storage:Battery": 1300.15,
    "Solar+Storage":   1682.997,
}

# Chart colors -- reused from `14 existing resource grouping.py`'s TECH_COLORS wherever a
# candidate tech_class matches an existing-fleet category (keeps the two figures visually
# consistent); new colors picked for the two tech_classes with no existing-fleet counterpart.
CANDIDATE_TECH_COLORS: dict[str, str] = {
    "Solar:PV":        "#FDB863",   # reused from Script 14
    "Wind":            "#74C476",   # reused from Script 14
    "Storage:Battery": "#9970AB",   # reused from Script 14
    "Gas:CT":          "#4393C3",   # reused from Script 14
    "Gas:CC":          "#455A64",   # reused from Script 14
    "Nuclear:SMR":     "#762A83",   # reused from Script 14's "Nuclear"
    "Solar+Storage":   "#C51B7D",   # new -- distinct from Solar's orange and Battery's purple
    "Geothermal":      "#E31A1C",   # new -- distinct red, no clash with existing colors
}

# ATB's documented long-term inflation assumption (2024 v3 Workbook, "Financial Definitions"
# sheet, cell D78: "2.5% in ReEDS"; confirmed as the literal value in "WACC Calc") -- used only
# to fill CRF for tech_classes ATB doesn't publish a CRF for directly (see module docstring).
ATB_INFLATION_RATE = 0.025


def compute_crf_from_wacc(wacc_nominal: float, crpyears: float) -> float:
    """ATB's own CRF formula (module docstring has full citation/verification) -- real WACC via
    the Fisher relation, then the standard capital recovery factor. Only used as a fallback when
    ATB doesn't publish CRF directly for a tech_class/case; matches ATB's published CRF exactly
    for every technology checked where a direct value exists to compare against."""
    wacc_real = (1 + wacc_nominal) / (1 + ATB_INFLATION_RATE) - 1
    return wacc_real / (1 - (1 + wacc_real) ** (-crpyears))


# ATB has no published capacity factor for these three technologies (they're dispatchable --
# utilization is a market/dispatch outcome, not a fixed technology trait ATB can characterize
# independent of a specific system study). Matches the reference CF values already established
# in `16 om costs.py`'s REF_CF dict, reused here for consistency rather than inventing new ones.
REF_CF_FALLBACK: dict[str, float] = {
    "Gas:CT":          0.15,
    "Gas:CC":          0.50,
    "Storage:Battery": 0.25,
}


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


def load_atb_raw(csv_path: Path) -> pd.DataFrame:
    """Load ATB CSV; filter to Moderate/Market scenario and the parameters/years we need."""
    print("  Loading ATB 2024 (large file -- may take a moment)...")
    df = pd.read_csv(csv_path, low_memory=False)

    df["scenario"]             = df["scenario"].str.lower().str.strip()
    df["core_metric_variable"] = pd.to_numeric(df["core_metric_variable"], errors="coerce")
    df["value"]                = pd.to_numeric(df["value"], errors="coerce")
    df["crpyears"]             = pd.to_numeric(df["crpyears"], errors="coerce")

    # Some pure financing-policy parameters (e.g. Tax Rate) are scenario-independent and
    # tagged scenario="*" in ATB rather than "moderate" -- keep those alongside Moderate.
    mask = (
        (df["scenario"].isin([ATB_SCENARIO, "*"]))
        & (df["core_metric_case"] == ATB_CASE)
        & (df["core_metric_parameter"].isin(ATB_PARAMS))
        & (df["core_metric_variable"].isin(ATB_YEARS))
    )
    filtered = df[mask].copy()
    print(f"  Filtered to {len(filtered):,} rows (Moderate, Market, {ATB_PARAMS[0]}..{ATB_PARAMS[-1]}, "
          f"{ATB_YEARS[0]}-{ATB_YEARS[-1]})")
    return filtered


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _select(
    df: pd.DataFrame,
    technology: str,
    techdetail: str,
    param: str,
    year: int,
    crpyears: int,
    tax_credit_case: str | None,
) -> float | None:
    """Median ATB value for a technology/techdetail/parameter/year/crpyears combination.
    tax_credit_case=None skips filtering on that column (technologies with no tax-credit
    dimension report it as NaN, which a `==` filter would otherwise incorrectly drop)."""
    mask = (
        (df["technology"] == technology)
        & (df["techdetail"] == techdetail)
        & (df["core_metric_parameter"] == param)
        & (df["core_metric_variable"] == year)
        & (df["crpyears"] == crpyears)
    )
    if tax_credit_case is not None:
        mask &= (df["tax_credit_case"] == tax_credit_case)

    vals = df[mask]["value"].dropna()
    if vals.empty:
        return None
    return float(vals.median())


def build_candidate_lookup(atb: pd.DataFrame) -> pd.DataFrame:
    """For each candidate tech_class x year: extract OCC, Fixed O&M, Variable O&M, Heat Rate,
    CF (cost/perf, at the tech's own cost_techdetail) and Debt Fraction, Interest Rate, ROE,
    Tax Rate, WACC, CRF (financing, at techdetail='*' -- borrowed from another tech_class for
    Storage:Battery, which has no financing block of its own)."""
    rows = []

    for tech_class, spec in TECH_SPEC.items():
        borrow_from = spec.get("borrow_financing_from")
        if borrow_from:
            fin_spec = TECH_SPEC[borrow_from]
            fin_technology, fin_crp, fin_tcc = (
                fin_spec["atb_technology"], fin_spec["crpyears"], fin_spec.get("tax_credit_case"),
            )
        else:
            fin_technology, fin_crp, fin_tcc = (
                spec["atb_technology"], spec["crpyears"], spec.get("tax_credit_case"),
            )

        for year in ATB_YEARS:
            occ = _select(
                atb, spec["atb_technology"], spec["cost_techdetail"], "OCC",
                year, spec["crpyears"], spec.get("tax_credit_case"),
            )
            if occ is None:
                continue   # e.g. Nuclear before ATB's 2030 start year

            capex = _select(
                atb, spec["atb_technology"], spec["cost_techdetail"], "CAPEX",
                year, spec["crpyears"], spec.get("tax_credit_case"),
            )
            fixed_om = _select(
                atb, spec["atb_technology"], spec["cost_techdetail"], "Fixed O&M",
                year, spec["crpyears"], spec.get("tax_credit_case"),
            )
            vom = _select(
                atb, spec["atb_technology"], spec["cost_techdetail"], "Variable O&M",
                year, spec["crpyears"], spec.get("tax_credit_case"),
            )
            heat_rate = (
                _select(
                    atb, spec["atb_technology"], spec["cost_techdetail"], "Heat Rate",
                    year, spec["crpyears"], spec.get("tax_credit_case"),
                ) if spec.get("has_heat_rate") else None
            )
            cf = _select(
                atb, spec["atb_technology"], spec["cost_techdetail"], "CF",
                year, spec["crpyears"], spec.get("tax_credit_case"),
            )

            debt_fraction = _select(atb, fin_technology, "*", "Debt Fraction", year, fin_crp, fin_tcc)
            interest_rate = _select(atb, fin_technology, "*", "Interest Rate Nominal", year, fin_crp, fin_tcc)
            roe           = _select(atb, fin_technology, "*", "Rate of Return on Equity Nominal", year, fin_crp, fin_tcc)
            tax_rate      = _select(atb, fin_technology, "*", "Tax Rate (Federal and State)", year, fin_crp, fin_tcc)
            wacc          = _select(atb, fin_technology, "*", "WACC Nominal", year, fin_crp, fin_tcc)
            crf           = _select(atb, fin_technology, "*", "CRF", year, fin_crp, fin_tcc)

            if crf is not None:
                crf_source = "atb_published"
            elif wacc is not None:
                crf = compute_crf_from_wacc(wacc, fin_crp)
                crf_source = "computed_real_wacc"
            else:
                crf_source = None

            rows.append({
                "tech_class":              tech_class,
                "atb_year":                year,
                "scenario":                "Moderate",
                "occ_per_kw":              round(occ, 2),
                "capex_per_kw":            round(capex, 2) if capex is not None else None,
                "fixed_om_per_kw_yr":      round(fixed_om, 2) if fixed_om is not None else None,
                "variable_om_per_mwh":     round(vom, 4) if vom is not None else None,
                "heat_rate_mmbtu_per_mwh": round(heat_rate, 4) if heat_rate is not None else None,
                "atb_cf":                  round(cf, 4) if cf is not None else None,
                "debt_fraction":           round(debt_fraction, 4) if debt_fraction is not None else None,
                "interest_rate_nominal":   round(interest_rate, 4) if interest_rate is not None else None,
                "roe_nominal":             round(roe, 4) if roe is not None else None,
                "tax_rate":                round(tax_rate, 4) if tax_rate is not None else None,
                "wacc_nominal":            round(wacc, 4) if wacc is not None else None,
                "crf":                     round(crf, 4) if crf is not None else None,
                "crf_source":              crf_source,
                "crpyears":                spec["crpyears"],
                "atb_technology":          spec["atb_technology"],
                "atb_techdetail":          spec["cost_techdetail"],
                "tax_credit_case":         spec.get("tax_credit_case") or "",
                "financing_source":        borrow_from or tech_class,
            })

    return pd.DataFrame(rows)


def add_hybrid_split(lookup: pd.DataFrame) -> pd.DataFrame:
    """Adds hybrid_solar_occ_share / hybrid_battery_occ_share to the Solar+Storage rows,
    computed per year from the standalone Solar:PV and Storage:Battery OCC values."""
    lookup = lookup.copy()
    lookup["hybrid_solar_occ_share"]    = None
    lookup["hybrid_battery_occ_share"]  = None

    solar_occ = lookup[lookup["tech_class"] == "Solar:PV"].set_index("atb_year")["occ_per_kw"]
    batt_occ  = lookup[lookup["tech_class"] == "Storage:Battery"].set_index("atb_year")["occ_per_kw"]
    years     = sorted(set(solar_occ.index) & set(batt_occ.index))

    hybrid_mask = lookup["tech_class"] == "Solar+Storage"
    for year in years:
        s, b  = float(solar_occ.loc[year]), float(batt_occ.loc[year])
        total = s + b
        row_mask = hybrid_mask & (lookup["atb_year"] == year)
        lookup.loc[row_mask, "hybrid_solar_occ_share"]   = round(s / total, 4)
        lookup.loc[row_mask, "hybrid_battery_occ_share"] = round(b / total, 4)

    return lookup


# ---------------------------------------------------------------------------
# Summary / verification
# ---------------------------------------------------------------------------

def print_summary(lookup: pd.DataFrame) -> None:
    print(f"\n  Rows by tech_class:")
    print(f"  {'tech_class':<18} {'n_years':>7} {'first_yr':>8} {'last_yr':>7} "
          f"{'OCC first':>10} {'OCC last':>9}")
    print(f"  {'-'*64}")
    for tech_class in TECH_SPEC:
        sub = lookup[lookup["tech_class"] == tech_class].sort_values("atb_year")
        if sub.empty:
            print(f"  {tech_class:<18}  NO ROWS EXTRACTED -- check TECH_SPEC filters")
            continue
        first, last = sub.iloc[0], sub.iloc[-1]
        print(
            f"  {tech_class:<18} {len(sub):>7} {int(first['atb_year']):>8} {int(last['atb_year']):>7} "
            f"{first['occ_per_kw']:>10,.1f} {last['occ_per_kw']:>9,.1f}"
        )

    print(f"\n  Financing coverage @ 2030 (blank = intentionally borrowed/unavailable):")
    print(f"  {'tech_class':<18} {'DebtFrac':>9} {'IntRate':>8} {'ROE':>7} {'TaxRate':>8} {'CRF':>7} {'crf_source':<20} {'financing_source'}")
    print(f"  {'-'*95}")
    at_2030 = lookup[lookup["atb_year"] == 2030].set_index("tech_class")
    for tech_class in TECH_SPEC:
        if tech_class not in at_2030.index:
            continue
        r = at_2030.loc[tech_class]
        df_s  = f"{r['debt_fraction']:.1%}" if pd.notna(r["debt_fraction"]) else "  --"
        ir_s  = f"{r['interest_rate_nominal']:.1%}" if pd.notna(r["interest_rate_nominal"]) else "  --"
        roe_s = f"{r['roe_nominal']:.1%}" if pd.notna(r["roe_nominal"]) else "  --"
        tax_s = f"{r['tax_rate']:.1%}" if pd.notna(r["tax_rate"]) else "  --"
        crf_s = f"{r['crf']:.4f}" if pd.notna(r["crf"]) else "  --"
        print(f"  {tech_class:<18} {df_s:>9} {ir_s:>8} {roe_s:>7} {tax_s:>8} {crf_s:>7} {str(r['crf_source']):<20} {r['financing_source']}")

    print(f"\n  OCC vs. CAPEX @ 2030 (gap = GCC + capitalized interest during construction):")
    print(f"  {'tech_class':<18} {'OCC':>10} {'CAPEX':>10} {'Gap':>9}")
    print(f"  {'-'*50}")
    for tech_class in TECH_SPEC:
        if tech_class not in at_2030.index:
            continue
        r = at_2030.loc[tech_class]
        if pd.isna(r["capex_per_kw"]):
            print(f"  {tech_class:<18} {r['occ_per_kw']:>10,.1f}  (no CAPEX reported)")
            continue
        gap = r["capex_per_kw"] - r["occ_per_kw"]
        print(f"  {tech_class:<18} {r['occ_per_kw']:>10,.1f} {r['capex_per_kw']:>10,.1f} {gap:>9,.1f}")

    hybrid = lookup[lookup["tech_class"] == "Solar+Storage"].sort_values("atb_year")
    if not hybrid.empty:
        sums = (hybrid["hybrid_solar_occ_share"] + hybrid["hybrid_battery_occ_share"]).dropna()
        bad  = (sums - 1.0).abs() > 1e-6
        print(
            f"\n  Hybrid OCC split (n={len(hybrid)} years): shares sum to 1.0 in "
            f"{(~bad).sum()}/{len(sums)} years"
        )
        r2030 = hybrid[hybrid["atb_year"] == 2030]
        if not r2030.empty:
            row = r2030.iloc[0]
            print(
                f"  2030 example: solar {row['hybrid_solar_occ_share']:.1%} / "
                f"battery {row['hybrid_battery_occ_share']:.1%}"
            )

    print(f"\n  Spot-check vs. values surfaced during plan review (2030, Moderate):")
    at_2030_occ = lookup[lookup["atb_year"] == 2030].set_index("tech_class")["occ_per_kw"]
    for tech_class, expected in SPOT_CHECK_2030_OCC.items():
        actual = at_2030_occ.get(tech_class)
        status = "OK" if actual is not None and abs(actual - expected) < 0.5 else "MISMATCH"
        print(f"  {tech_class:<18} expected ${expected:>9,.2f}/kW  actual ${actual:>9,.2f}/kW  [{status}]")


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
# Styling matches `14 existing resource grouping.py`'s save_chart() (Times New Roman, legend
# outside the frame, top/right spines removed) so both figures read as one visual family.

CAPEX_PLOT_OUT = DATA_CLEANING / "resources" / "costs" / "candidate_capex_projections.png"
OM_PLOT_OUT    = DATA_CLEANING / "resources" / "costs" / "candidate_om_projections.png"

PLOT_FONT_SIZE      = 22   # axis titles, legend
PLOT_TICK_LABELSIZE = 20   # numeric axis tick labels


def plot_capex_trajectories(lookup: pd.DataFrame, out_path: Path) -> None:
    """One line per tech_class: total CAPEX ($/kW) vs. atb_year."""
    import matplotlib.pyplot as plt

    with plt.rc_context({"font.family": "Times New Roman", "font.size": PLOT_FONT_SIZE}):
        fig, ax = plt.subplots(figsize=(10, 6))

        for tech_class in TECH_SPEC:
            sub = lookup[lookup["tech_class"] == tech_class].sort_values("atb_year")
            sub = sub.dropna(subset=["capex_per_kw"])
            if sub.empty:
                continue
            ax.plot(
                sub["atb_year"], sub["capex_per_kw"],
                marker="o", markersize=4, linewidth=2,
                color=CANDIDATE_TECH_COLORS[tech_class], label=tech_class,
            )

        ax.set_xlabel("Year", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("Total CAPEX ($/kW)", fontsize=PLOT_FONT_SIZE)
        ax.tick_params(axis="both", labelsize=PLOT_TICK_LABELSIZE)
        ax.spines[["top", "right"]].set_visible(False)

        handles, labels = ax.get_legend_handles_labels()
        ax.legend(
            handles[::-1], labels[::-1],
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            fontsize=PLOT_FONT_SIZE,
            frameon=False,
            borderpad=0.8,
            labelspacing=0.5,
        )

        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    print(f"  Chart -> {out_path.name}")


def plot_om_trajectories(lookup: pd.DataFrame, out_path: Path) -> None:
    """One line per tech_class: combined annual O&M ($/kW-yr) vs. atb_year, where
    combined = fixed_om_per_kw_yr + variable_om_per_mwh * 8760 * CF / 1000.
    CF is the lookup's own atb_cf where populated, else REF_CF_FALLBACK."""
    import matplotlib.pyplot as plt

    with plt.rc_context({"font.family": "Times New Roman", "font.size": PLOT_FONT_SIZE}):
        fig, ax = plt.subplots(figsize=(10, 6))

        for tech_class in TECH_SPEC:
            sub = lookup[lookup["tech_class"] == tech_class].sort_values("atb_year").copy()
            if sub.empty:
                continue

            cf = sub["atb_cf"].fillna(REF_CF_FALLBACK.get(tech_class))
            vom = sub["variable_om_per_mwh"].fillna(0.0)
            fixed = sub["fixed_om_per_kw_yr"].fillna(0.0)
            annual_om = fixed + vom * 8760 * cf / 1000

            ax.plot(
                sub["atb_year"], annual_om,
                marker="o", markersize=4, linewidth=2,
                color=CANDIDATE_TECH_COLORS[tech_class], label=tech_class,
            )

        ax.set_xlabel("Year", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("Combined Annual O&M ($/kW-yr)", fontsize=PLOT_FONT_SIZE)
        ax.tick_params(axis="both", labelsize=PLOT_TICK_LABELSIZE)
        ax.spines[["top", "right"]].set_visible(False)

        handles, labels = ax.get_legend_handles_labels()
        ax.legend(
            handles[::-1], labels[::-1],
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            fontsize=PLOT_FONT_SIZE,
            frameon=False,
            borderpad=0.8,
            labelspacing=0.5,
        )

        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    print(f"  Chart -> {out_path.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Build candidate technology cost/financing data.")
    parser.add_argument(
        "--redownload", action="store_true",
        help="Force a fresh ATB download even if a cached copy already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print("\n--- Script 20: Candidate Technology Cost & Financing Data (ATB 2024) ---")

    print("\n[1/4] Loading ATB 2024 raw data...")
    atb = load_atb_raw(download_atb(force=args.redownload))

    print("\n[2/4] Extracting candidate technology cost/performance/financing trajectories...")
    lookup = build_candidate_lookup(atb)
    n_missing = [tc for tc in TECH_SPEC if lookup[lookup["tech_class"] == tc].empty]
    if n_missing:
        raise ValueError(f"No rows extracted for: {n_missing} -- check TECH_SPEC filters")

    print("\n[3/4] Computing hybrid solar+storage OCC split...")
    lookup = add_hybrid_split(lookup)

    print("\n[4/4] Saving output...")
    ATB_OUT.parent.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(ATB_OUT, index=False)
    print(f"  Saved: {ATB_OUT.relative_to(PROJECT_ROOT)}  ({len(lookup)} rows)")

    print_summary(lookup)

    print("\nSaving diagnostic charts...")
    plot_capex_trajectories(lookup, CAPEX_PLOT_OUT)
    plot_om_trajectories(lookup, OM_PLOT_OUT)


if __name__ == "__main__":
    main()
