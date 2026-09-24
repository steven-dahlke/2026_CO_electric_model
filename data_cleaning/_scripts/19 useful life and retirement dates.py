"""
Script 19: Useful Life and Retirement Dates

Enriches colorado_resources.csv (Script 18 output) with RetirementDate for existing
resources that don't already have one. Per the 2026-07-15 decision, existing resources
retire at the end of an assumed useful life (RetirementDate), not via EnCompass's own
economic-retirement optimization (MaxRetire stays at its default of 0, not added).

New columns: RetirementDate (fills blanks only — never overwrites an announced EIA-860
date), retirement_life_source.

Also exports data_cleaning/resources/retirement_life_assumptions_table.docx — a bare
Word table (no title/note, added manually in the manuscript) summarizing the
technology-class operating life assumptions below, styled to match the manuscript's
own "List Table 3" table style, for pasting directly into the writeup.

────────────────────────────────────────────────────────────────────────────
Sub-plan A — FERC Form 1 Schedule 336 depreciation-study service life
────────────────────────────────────────────────────────────────────────────
6 resources assigned from FERC Form 1 Schedule 336 (depreciation factors), the same
PUDL S3 catalog already used for O&M in Script 16.
  Source: core_ferc1__yearly_depreciation_factors_sched336 (PUDL S3, stable release)
  Saved:  data_cleaning/resources/costs/form1/raw/
          core_ferc1__yearly_depreciation_factors_sched336.csv

RetirementDate = CommissionDate + service_life_avg (years), rounded to whole years.
Only resources with high-confidence single-account or plant-level matches are included
here — ambiguous or unreliable matches are left for manual review, not guessed at.

Used only for Other Production (thermal, Gas:CC turbine side) accounts. Two other
Form 1-derived treatments were tried and deliberately dropped for consistency:
  - Hydro Production (113 yr, PSCo blended) — replaced by ATB's Hydropower Tech Life
    CRP (100 yr, Sub-plan B1 below), 2026-07-15, for consistency with how hydro is
    treated across the rest of the fleet and with candidate-resource assumptions.
  - Steam Production (59 yr, PSCo blended, was applied to pawnee__1 only) — removed
    2026-07-16. Keeping it meant Gas:ST was split across two different treatments
    (one resource on a Form 1 life, three others on the generic 30 yr gas assumption)
    for no strong reason — the Steam Production account is itself just PSCo's whole
    steam fleet blended average, no more authoritative than the generic assumption.
    pawnee__1 now uses the generic Gas:ST treatment (Sub-plan B2) like the rest of
    its TechType.

Coal (comanche_co__3):
  Public Service Co. of Oklahoma (utility_id_ferc1=205, a Comanche co-owner) reports
  Comanche as a named plant within its Other Production/Steam Production accounts,
  service_life_avg = 62 yr, stable across 2023-2024. Comanche's other two units
  (comanche_co__2) already carry an announced EIA-860 RetirementDate and are not
  touched here.

Gas:CC CA rows (cherokee__7, fort_st_vrain__1, rocky_mountain_energy_center__STG1):
  Combined-cycle plants split across two FERC accounts with different assumed lives:
  Steam Production (HRSG/steam-turbine side, 59 yr) vs. Other Production (combustion-
  turbine side, 45 yr). Form 1 still assigns Other Production (45 yr) to these three
  CAs first. align_ca_retirement_to_linked_cts() then overwrites each CA
  RetirementDate to the last linked CT (WasteHeat), so the steam turbine cannot
  outlive the CTs that feed it. The 45 yr figure remains the CT-side class
  assumption in the manuscript table; it is not the CA operating date.

────────────────────────────────────────────────────────────────────────────
Sub-plan A2 — Known policy-announced retirement, not in EIA-860 or Form 1
────────────────────────────────────────────────────────────────────────────
comanche_co__3 (Comanche Unit 3, commissioned 2010): overridden to 2030-12-01,
superseding the Form 1 engineering-life estimate above (2072). Xcel's original
assumed retirement was ~2070 (consistent with Form 1's 62-year life landing at
2072 — a useful cross-check that the Form 1 number itself is reasonable). A series
of PUC settlements accelerated this: Xcel's Feb 2021 Clean Energy Plan filing
proposed 2040; a subsequent settlement moved it to 2035; a further 2022 settlement
moved it to close by January 1, 2031 (Colorado Sun, "Xcel Energy agrees to close
Pueblo's Comanche 3 coal plant by 2031," 2022-04-26). RetirementDate set to
2030-12-01 (last full month of operation under a "close by Jan 1, 2031" commitment).
Note: a March 2026 Colorado Sun article reports Xcel has floated running coal
longer amid supply-gap concerns, and Unit 3 had an unplanned turbine outage in
2025 — the 2031 commitment is the current formally agreed date, not fully certain
to hold; revisit if the settlement changes.

Cross-check only (not applied — these resources already have an announced
RetirementDate from EIA-860, which takes precedence):
  craig_co__1 and cherokee__4 land within ~6 months of their Form 1-implied date.
  craig_co__2/3 and comanche_co__2 are retiring 11-15 years before their Form 1
  nominal life would suggest — consistent with policy/economics-driven early coal
  retirement (SB19-236 era) rather than physical end-of-life. hayden__1/2 were checked
  but excluded — PacifiCorp's five sub-account values for Hayden span 21-51 years with
  no clear single representative figure; a naive average isn't defensible the way
  Craig's turbogenerator-account match was.

NOTE: utility_id_ferc1 = 40 is excluded from all Schedule 336 matching. Its
depreciation rows are clearly a different (Texas) utility's data ("lignite",
"nuclear", pre-2000 only) despite Script 16 using that same ID successfully for
Schedule 402 — FERC utility ID consistency is not guaranteed across schedules.

────────────────────────────────────────────────────────────────────────────
Sub-plan B1 — NREL ATB 2024 Tech Life CRP (non-thermal technologies)
────────────────────────────────────────────────────────────────────────────
54 resources assigned from NREL ATB 2024's published "Tech Life CRP" (cost recovery
period) assumptions, provided directly by the user from the ATB workbook (not derived
from the flat file — the flat file's CRPyears field offers multiple options per
technology with no single value flagged as default; this table is ATB's own stated
default per technology):

  Hydropower: 100 yr | Pumped Storage Hydropower: 100 yr | Land-Based Wind: 30 yr
  Solar - Utility PV: 30 yr | Utility Scale Battery: 15 yr | Nuclear: 60 yr
  Geothermal: 30 yr

Applied as RetirementDate = CommissionDate + tech_life. Covers TechType in
{Hydro, Hydro:Pumped, Solar:PV, Wind, Storage:Battery}. 15 of the 54 are `proposed`
(not-yet-built) resources with no CommissionDate yet — expected, not an error; skipped
until they're actually built and get a real commission date.

Nuclear and Geothermal (added 2026-07-16) are recorded in ATB_TECH_LIFE for future
Phase 3 candidate-resource use but assign nothing today — no existing resource has
either TechType. ATB's flat file confirms "Nuclear - Small" (SMR) offers the identical
CRP options as "Nuclear - Large" (20/30/60 yr); no distinct SMR figure exists in ATB.

Cross-check: Hydro Production accounts land at 100 yr in ATB vs. 113 yr in PSCo's own
Form 1 filing (see Sub-plan A note above) — reasonably close, and both numbers are
financial/depreciation-style asset-life assumptions rather than physical wear-out
estimates, so the comparison is a fair one despite the different source.

────────────────────────────────────────────────────────────────────────────
Sub-plan B2 — thermal (Gas:CT/CC/ST/IC) generic fallback
────────────────────────────────────────────────────────────────────────────
Up to 43 resources (29 Gas:CT, 6 Gas:IC, 4 Gas:CC, 4 Gas:ST — including pawnee__1,
now that its Form 1 Steam Production treatment was removed) have no Form 1 coverage
(no Form 1 filing at all, or not one of the specific plants matched in Sub-plan A) and
no EIA-860 announced date. The ATB Tech Life CRP table used for Sub-plan B1 has no
gas/coal category. 30 years for all gas TechTypes (Gas:CT, Gas:CC, Gas:ST, Gas:IC)
was originally a direct unsourced assumption (2026-07-16), then confirmed the same
day against a reputable source: EIA, "Levelized Costs of New Generation Resources in
the Annual Energy Outlook 2026," p.3 — "The levelized costs are calculated based on a
30-year cost recovery period... for the 2031 online year," applied by EIA uniformly
across all new-build technologies including natural gas combined-cycle and combustion
turbine by name. Source label `eia_aeo2026_30yr_cost_recovery`. Same category of
assumption as the ATB Tech Life figures above (financial/cost-recovery convention, not
physical wear-out) — just from EIA instead of NREL for this row. The number itself
didn't change (already 30), so no retirement dates changed, only the citation.

Floor for past-dated results: 9 of these resources are small grouped Gas:ST/Gas:IC
units (plus one Gas:CT) old enough that their capacity-weighted CommissionDate + 30 yr
already precedes today -- e.g. North_PSCO_GasST_small averages ~49 years old already,
so a 30-year life computes a retirement date decades in the past for a resource that's
currently operating. Any such result is floored to 2030-12-01 instead (see
_floor_if_past()) -- chosen as roughly when the first wave of new capacity from this
initial model's own capacity-expansion results would plausibly come online, avoiding
an implied capacity gap at the start of a run. Source label gets a `_floored_2030`
suffix (e.g. `eia_aeo2026_30yr_cost_recovery_floored_2030`) so floored resources stay
distinguishable from ones where the 30-year computation landed in the future on its own.
"""

import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT  = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"
RESOURCES_CSV = DATA_CLEANING / "resources" / "colorado_resources.csv"
LIFE_TABLE_DOCX = DATA_CLEANING / "resources" / "retirement_life_assumptions_table.docx"

# ---------------------------------------------------------------------------
# Sub-plan A — FERC Form 1 Schedule 336 service life lookup
# Values and sourcing documented in the module docstring above.
# ---------------------------------------------------------------------------
FORM1_RETIREMENT_LIFE: dict[str, tuple[float, str]] = {
    "cherokee__7":                       ( 45.0, "form1_sched336_psco_other_production_2023"),
    "fort_st_vrain__1":                  ( 45.0, "form1_sched336_psco_other_production_2023"),
    "rocky_mountain_energy_center__STG1":( 45.0, "form1_sched336_psco_other_production_2023"),
    # comanche_co__3 intentionally NOT here — see MANUAL_POLICY_RETIREMENTS below.
    # Its Form 1 engineering-life estimate (62 yr -> 2072) is documented in the
    # module docstring as a cross-check, but the actual PUC settlement date
    # supersedes it.
    # Hydro:Pumped (Cabin Creek A/B, Mount Elbert 1/2, Flatiron 3) intentionally NOT
    # here — now sourced from ATB_TECH_LIFE below instead of PSCo's Form 1 figure.
    # pawnee__1 intentionally NOT here (removed 2026-07-16) — the PSCo Steam
    # Production figure (59 yr) was the only Form 1 treatment applying to
    # Gas:ST, which made the class inconsistent (one Gas:ST resource on a
    # Form 1 life, three others on the generic 30 yr gas assumption). Dropped
    # for consistency; pawnee__1 now falls through to the generic Gas:ST
    # assumption in ATB_TECH_LIFE like the rest of its TechType.
}

# ---------------------------------------------------------------------------
# Sub-plan B1 — NREL ATB 2024 Tech Life CRP (per user-provided ATB workbook table)
# Values and sourcing documented in the module docstring above.
# ---------------------------------------------------------------------------
ATB_TECH_LIFE: dict[str, tuple[float, str]] = {
    "Hydro":           (100.0, "atb_2024_tech_life"),
    "Hydro:Pumped":    (100.0, "atb_2024_tech_life"),
    "Solar:PV":        ( 30.0, "atb_2024_tech_life"),
    "Wind":            ( 30.0, "atb_2024_tech_life"),
    "Storage:Battery": ( 15.0, "atb_2024_tech_life"),
    # Nuclear and Geothermal (added 2026-07-16): no existing resource has
    # either TechType today, so these are inert until Phase 3 candidate
    # resources are built -- recorded now so that work doesn't need to
    # re-derive them. ATB's flat file confirms "Nuclear - Small" (SMR) offers
    # the identical CRP options as "Nuclear - Large" (20/30/60 yr) -- no
    # distinct SMR figure exists in ATB, so 60 yr is used for both. TechType
    # label here is a placeholder guess ("Nuclear"/"Geothermal") pending
    # whatever naming convention Phase 3 candidate resources actually use.
    "Nuclear":         ( 60.0, "atb_2024_tech_life"),
    "Geothermal":      ( 30.0, "atb_2024_tech_life"),
    # Utility-Scale PV-Plus-Battery (added 2026-07-16): same rationale as
    # Nuclear/Geothermal above -- forward-looking for the Phase 3 hybrid
    # solar+storage candidate, inert today, key name matches ATB's own
    # technology label.
    "Utility-Scale PV-Plus-Battery": (30.0, "atb_2024_tech_life"),
    # Sub-plan B2 — gas (Gas:CT/CC/ST/IC): 30 yr. Originally a direct
    # unsourced assumption (2026-07-16); confirmed against EIA's "Levelized
    # Costs of New Generation Resources in the Annual Energy Outlook 2026"
    # (2026-07-16 also) -- p.3: "The levelized costs are calculated based on a
    # 30-year cost recovery period... for the 2031 online year," applied
    # uniformly by EIA across all new-build technologies including natural
    # gas combined-cycle and combustion turbine. Same category of assumption
    # as ATB's Tech Life figures above (financial/cost-recovery convention,
    # not physical wear-out) -- just from EIA instead of NREL for this row,
    # and it happens to land on the same 30-year figure already in use, so no
    # retirement dates changed, only the citation.
    "Gas:CT": (30.0, "eia_aeo2026_30yr_cost_recovery"),
    "Gas:CC": (30.0, "eia_aeo2026_30yr_cost_recovery"),
    "Gas:ST": (30.0, "eia_aeo2026_30yr_cost_recovery"),
    "Gas:IC": (30.0, "eia_aeo2026_30yr_cost_recovery"),
}

# ---------------------------------------------------------------------------
# Sub-plan A2 — known policy-announced retirements not captured in EIA-860 or
# Form 1. Takes precedence over both. Sourcing documented in the module
# docstring above.
# ---------------------------------------------------------------------------
MANUAL_POLICY_RETIREMENTS: dict[str, tuple[str, str]] = {
    "comanche_co__3": ("2030-12-01", "xcel_puc_settlement_close_by_2031"),
}


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

def _add_years(d: date, years: float) -> date:
    y = d.year + int(round(years))
    try:
        return date(y, d.month, d.day)
    except ValueError:
        return date(y, d.month, 28)   # Feb 29 -> Feb 28 fallback


# Floor for computed dates landing in the past (added 2026-07-16). Some older
# small grouped gas resources (Gas:ST/Gas:IC especially) have a capacity-
# weighted CommissionDate old enough that CommissionDate + 30 yr already
# precedes today -- physically wrong for a resource that's currently
# operating. Floored to 2030-12-01 rather than left as computed: that's about
# when the first wave of new capacity from this initial model's capacity-
# expansion results would plausibly come online, so it avoids implying an
# immediate capacity gap at the start of a run.
RETIREMENT_FLOOR = date(2030, 12, 1)


def _floor_if_past(rdate: date) -> tuple[date, bool]:
    if rdate < date.today():
        return RETIREMENT_FLOOR, True
    return rdate, False


def assign_form1_retirement_dates(resources: pd.DataFrame) -> pd.DataFrame:
    print("\n[RetirementDate] Assigning from FERC Form 1 Schedule 336 useful life ...")
    resources = resources.copy()

    if "retirement_life_source" not in resources.columns:
        resources["retirement_life_source"] = pd.NA

    assigned, skipped_has_date, skipped_no_commission = [], [], []
    for idx, row in resources.iterrows():
        name = str(row["Name"])
        if name not in FORM1_RETIREMENT_LIFE:
            continue

        if pd.notna(row.get("RetirementDate")) and str(row.get("RetirementDate")).strip():
            skipped_has_date.append(name)
            continue

        comm = row.get("CommissionDate")
        if pd.isna(comm) or not str(comm).strip():
            skipped_no_commission.append(name)
            continue

        life, source = FORM1_RETIREMENT_LIFE[name]
        cdate = date.fromisoformat(str(comm)[:10])
        rdate = _add_years(cdate, life)

        resources.at[idx, "RetirementDate"]        = rdate.isoformat()
        resources.at[idx, "retirement_life_source"] = source
        assigned.append((name, life, rdate.isoformat(), source))

    print(f"  Assigned: {len(assigned)}")
    for name, life, rdate, source in assigned:
        print(f"    {name:<38} {life:>5.0f} yr -> {rdate}  ({source})")
    if skipped_has_date:
        print(f"  Skipped (already has RetirementDate): {skipped_has_date}")
    if skipped_no_commission:
        print(f"  *** Skipped (no CommissionDate to add life to): {skipped_no_commission}")

    return resources


def assign_atb_tech_life_retirement_dates(resources: pd.DataFrame) -> pd.DataFrame:
    print("\n[RetirementDate] Assigning from ATB 2024 Tech Life CRP ...")
    resources = resources.copy()

    assigned, floored, skipped_has_date, skipped_no_commission = [], [], [], []
    for idx, row in resources.iterrows():
        tech = row.get("TechType")
        if tech not in ATB_TECH_LIFE:
            continue

        if pd.notna(row.get("RetirementDate")) and str(row.get("RetirementDate")).strip():
            skipped_has_date.append(str(row["Name"]))
            continue

        comm = row.get("CommissionDate")
        if pd.isna(comm) or not str(comm).strip():
            skipped_no_commission.append(str(row["Name"]))
            continue

        life, source = ATB_TECH_LIFE[tech]
        cdate = date.fromisoformat(str(comm)[:10])
        rdate = _add_years(cdate, life)
        rdate, was_floored = _floor_if_past(rdate)
        if was_floored:
            source = source + "_floored_2030"
            floored.append((str(row["Name"]), tech, life))

        resources.at[idx, "RetirementDate"]        = rdate.isoformat()
        resources.at[idx, "retirement_life_source"] = source
        assigned.append((str(row["Name"]), tech, life, rdate.isoformat()))

    print(f"  Assigned: {len(assigned)}")
    for name, tech, life, rdate in assigned:
        print(f"    {name:<38} {tech:<16} {life:>5.0f} yr -> {rdate}")
    if floored:
        print(f"  Floored to {RETIREMENT_FLOOR.isoformat()} (computed date already in the past): "
              f"{len(floored)}  {[n for n, t, l in floored]}")
    if skipped_no_commission:
        print(f"  Skipped (no CommissionDate yet -- expected for 'proposed' resources): "
              f"{len(skipped_no_commission)}  {skipped_no_commission}")

    return resources


def assign_manual_policy_retirements(resources: pd.DataFrame) -> pd.DataFrame:
    print("\n[RetirementDate] Applying known policy-announced overrides ...")
    resources = resources.copy()

    for idx, row in resources.iterrows():
        name = str(row["Name"])
        if name not in MANUAL_POLICY_RETIREMENTS:
            continue
        rdate, source = MANUAL_POLICY_RETIREMENTS[name]
        prior = row.get("RetirementDate")
        prior_str = f" (was {prior})" if pd.notna(prior) and str(prior).strip() else ""
        resources.at[idx, "RetirementDate"]         = rdate
        resources.at[idx, "retirement_life_source"] = source
        print(f"    {name:<38} -> {rdate}{prior_str}  ({source})")

    return resources


def align_ca_retirement_to_linked_cts(resources: pd.DataFrame) -> pd.DataFrame:
    """Overwrite each CA RetirementDate to the last linked CT (WasteHeat).

    Form 1 45-year lives on the steam turbines vs ATB 30-year lives on the CTs
    otherwise leave orphaned CA rows (phantom RA and zero-CO2 MWh). Last CT, not
    first: remaining CTs can still feed steam. Does not delete CT/CA rows.
    """
    print("\n[RetirementDate] Aligning CA retirement to last linked CT ...")
    resources = resources.copy()
    wh = resources["WasteHeat"]
    linked = resources[wh.notna() & (wh.astype(str).str.strip() != "")].copy()
    linked["_ca"] = linked["WasteHeat"].astype(str)

    is_ca = resources["prime_mover"].astype(str) == "CA"
    n_aligned = 0
    for idx, ca in resources.loc[is_ca].iterrows():
        ca_name = str(ca["Name"])
        cts = linked.loc[linked["_ca"] == ca_name]
        if cts.empty:
            continue
        missing = cts["RetirementDate"].isna() | (cts["RetirementDate"].astype(str).str.strip() == "")
        if missing.any():
            bad = cts.loc[missing, "Name"].tolist()
            raise ValueError(
                f"Linked CTs for CA {ca_name} are missing RetirementDate: {bad}"
            )
        last = pd.to_datetime(cts["RetirementDate"]).max().date().isoformat()
        prior = ca.get("RetirementDate")
        prior_str = f" (was {prior})" if pd.notna(prior) and str(prior).strip() else ""
        resources.at[idx, "RetirementDate"] = last
        resources.at[idx, "retirement_life_source"] = "aligned_to_last_linked_ct"
        print(f"    {ca_name:<38} -> {last}{prior_str}")
        n_aligned += 1
    print(f"  Aligned: {n_aligned}")
    return resources


# ---------------------------------------------------------------------------
# Writeup export — technology class operating life assumptions table
# ---------------------------------------------------------------------------

WRITEUP_DOCX = PROJECT_ROOT / "Manuscript" / "methods v1.docx"


def export_life_assumptions_table(resources: pd.DataFrame, out_path: Path,
                                    writeup_docx: Path = WRITEUP_DOCX) -> None:
    """Write a bare Word table (no title/caption/note -- added manually in the
    manuscript) summarizing technology-class operating life assumptions. Doubles
    as the reference table for Phase 3 candidate-resource OpLife assumptions
    (Geothermal, Small Modular Reactor, PV+Battery hybrid) as well as existing-
    resource RetirementDate estimation -- that's why it has no resource-count
    column and includes technologies with no current resource. Life-years
    pulled live from FORM1_RETIREMENT_LIFE / ATB_TECH_LIFE so the table always
    matches the code.

    Styling: uses the manuscript's own "List Table 3" built-in Word table
    style (bold shaded header, banded rows) instead of manually approximating
    colors. python-docx's default blank-document template doesn't carry any
    built-in table styles, so this opens writeup_docx itself as the base
    document (inheriting its styles/theme), clears all body content, adds the
    table, and saves as a new file -- writeup_docx itself is never modified.
    """
    import docx
    from docx.enum.table import WD_ALIGN_VERTICAL
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Pt

    rows_data = [
        ("Technology Class", "Assumed Life (yr)", "Source"),
        ("Hydropower", f"{ATB_TECH_LIFE['Hydro'][0]:.0f}", "ATB"),
        ("Pumped Storage Hydropower", f"{ATB_TECH_LIFE['Hydro:Pumped'][0]:.0f}", "ATB"),
        ("Land-Based Wind", f"{ATB_TECH_LIFE['Wind'][0]:.0f}", "ATB"),
        ("Utility-Scale Solar PV", f"{ATB_TECH_LIFE['Solar:PV'][0]:.0f}", "ATB"),
        ("Utility-Scale Battery Storage", f"{ATB_TECH_LIFE['Storage:Battery'][0]:.0f}", "ATB"),
        ("Utility-Scale PV Plus Battery Hybrid",
         f"{ATB_TECH_LIFE['Utility-Scale PV-Plus-Battery'][0]:.0f}", "ATB"),
        ("Geothermal", f"{ATB_TECH_LIFE['Geothermal'][0]:.0f}", "ATB"),
        ("Small Modular Reactor", f"{ATB_TECH_LIFE['Nuclear'][0]:.0f}", "ATB"),
        ("Gas CC", f"{FORM1_RETIREMENT_LIFE['cherokee__7'][0]:.0f}", "Form 1"),
        ("Natural Gas CT", f"{ATB_TECH_LIFE['Gas:CT'][0]:.0f}", "EIA AEO"),
        ("Other Natural Gas", f"{ATB_TECH_LIFE['Gas:CC'][0]:.0f}", "EIA AEO"),
    ]

    if not writeup_docx.exists():
        raise FileNotFoundError(
            f"Can't find {writeup_docx} to borrow the 'List Table 3' style from. "
            f"Pass writeup_docx= explicitly if it's moved."
        )
    doc = docx.Document(writeup_docx)
    body = doc.element.body
    sectPr = body.find(qn("w:sectPr"))
    for child in list(body):
        if child is not sectPr:
            body.remove(child)

    table = doc.add_table(rows=len(rows_data), cols=3)
    table.style = "List Table 3"
    tblLook = table._tbl.tblPr.find(qn("w:tblLook"))
    if tblLook is None:
        from docx.oxml import OxmlElement
        tblLook = OxmlElement("w:tblLook")
        table._tbl.tblPr.append(tblLook)
    tblLook.set(qn("w:val"), "04A0")
    tblLook.set(qn("w:firstRow"), "1")
    tblLook.set(qn("w:lastRow"), "0")
    tblLook.set(qn("w:firstColumn"), "1")
    tblLook.set(qn("w:lastColumn"), "0")
    tblLook.set(qn("w:noHBand"), "0")
    tblLook.set(qn("w:noVBand"), "1")

    NUMERIC_COL = 1   # "Assumed Life (yr)" -- right aligned; all others left aligned
    for ri, row_vals in enumerate(rows_data):
        for ci, val in enumerate(row_vals):
            cell = table.cell(ri, ci)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            # Use the cell's existing (single, empty) run instead of cell.text=""
            # + add_run(), which left a stray empty <w:r/> ahead of the real run.
            run = p.runs[0] if p.runs else p.add_run()
            run.text = val
            run.font.size = Pt(10)
            if ri == 0:
                run.bold = True
            p.alignment = (WD_ALIGN_PARAGRAPH.RIGHT if ci == NUMERIC_COL
                            else WD_ALIGN_PARAGRAPH.LEFT)
            # Explicitly zero indentation -- direct formatting so it can't
            # inherit a left indent from the table style's conditional
            # (first-row/first-column) formatting.
            pf = p.paragraph_format
            pf.left_indent = pf.right_indent = pf.first_line_indent = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    print(f"\n  Wrote technology life assumptions table -> {out_path}")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def print_summary(resources: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("RETIREMENT DATE COVERAGE SUMMARY")
    print("=" * 72)
    n = len(resources)
    have_ret = resources["RetirementDate"].notna() & (resources["RetirementDate"].astype(str).str.strip() != "")
    print(f"\nTotal resources: {n}")
    print(f"  Have RetirementDate: {have_ret.sum()} / {n}")
    print(f"  Still without one:   {(~have_ret).sum()} / {n}  "
          f"(pending Sub-plan B generic fallback)")

    sources    = resources.loc[have_ret, "retirement_life_source"]
    announced  = sources.isna().sum()
    src_counts = sources.dropna().value_counts()
    print(f"\nBy source:")
    print(f"  EIA-860 announced (existing, unchanged): {announced}")
    for src, cnt in src_counts.items():
        print(f"  {src}: {cnt}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Script 19: Useful Life and Retirement Dates ===")

    resources = pd.read_csv(RESOURCES_CSV, dtype={"RetirementDate": str, "CommissionDate": str})
    print(f"  Loaded {len(resources)} resources from {RESOURCES_CSV.name}")

    # Reset stale values from deprecated sources so a fresh assignment can run below.
    # Without this, rows already filled by a prior run would be silently skipped by
    # every assignment function, since none of them overwrite an existing
    # RetirementDate.
    #   - form1_sched336_psco_hydro_2023: replaced by ATB Hydro Production (100 yr).
    #   - form1_sched336_psco_steam_2023: pawnee__1's Form 1 Steam Production figure
    #     (59 yr), removed 2026-07-16 so all Gas:ST resources use the same generic
    #     30 yr assumption -- see FORM1_RETIREMENT_LIFE comment.
    #   - assumed_30yr_gas / assumed_30yr_gas_floored_2030: relabeled 2026-07-16 to
    #     eia_aeo2026_30yr_cost_recovery(_floored_2030) once a citable source was
    #     found for the same 30 yr figure -- see ATB_TECH_LIFE Gas:* comment. The
    #     life-year value and computed dates are unchanged, only the source label.
    DEPRECATED_SOURCES = [
        "form1_sched336_psco_hydro_2023",
        "form1_sched336_psco_steam_2023",
        "assumed_30yr_gas",
        "assumed_30yr_gas_floored_2030",
    ]
    stale_mask = resources["retirement_life_source"].isin(DEPRECATED_SOURCES)
    if stale_mask.any():
        print(f"  Clearing {stale_mask.sum()} stale value(s) from deprecated sources: "
              f"{resources.loc[stale_mask, 'Name'].tolist()}")
        resources.loc[stale_mask, "RetirementDate"]         = pd.NA
        resources.loc[stale_mask, "retirement_life_source"] = pd.NA

    resources = assign_form1_retirement_dates(resources)
    resources = assign_atb_tech_life_retirement_dates(resources)
    resources = assign_manual_policy_retirements(resources)
    resources = align_ca_retirement_to_linked_cts(resources)

    print_summary(resources)

    resources.to_csv(RESOURCES_CSV, index=False)
    print(f"\n  Saved: {RESOURCES_CSV}")
    print(f"  New/updated columns: RetirementDate, retirement_life_source")

    export_life_assumptions_table(resources, LIFE_TABLE_DOCX)


if __name__ == "__main__":
    main()
