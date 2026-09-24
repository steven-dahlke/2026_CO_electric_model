# Resource Planning Work Plan

Living to-do list for existing-fleet finalization and candidate new-build resource
development. Captures the reasoning behind the sequencing, not just the tasks, so future
sessions don't have to re-derive it. See also:
`encompass_parameter_reference.md` (full EnCompass Resource/Project parameter reference) and
`costs/atb/atb_2024_technology_review.md` (ATB 2024 technology-by-technology review).

Status as of 2026-07-22.

---

## Phase 1 — Existing-resource EnCompass import template

**Goal:** get the existing fleet (`colorado_resources.csv`) actually importing and running in
EnCompass, before adding more complexity on top.

**Why first:** the file is more complete than it looked at a glance — every populated column
is fully filled for its applicable resource type (verified by fill-rate check, 2026-07-15).
`FixedRate`/`EnCost` (O&M) have zero blanks across all 121 rows — Script 20 (O&M costs) is
further along than the last status note in memory suggested; update that. The only true gap is
`FirmCap`, and that doesn't block a first import/run. Getting this running now de-risks five
scripts' worth of unvalidated analytical work (grouping, heat rates, emissions, O&M,
mincap/outages, storage) before candidate-resource complexity (Project sheet, financing, hybrid
pairing) is stacked on top of it.

**Decision (2026-07-15): existing resources retire at the end of their useful life
(`RetirementDate`), not via the model's own economic-retirement optimization.** `MaxRetire`
stays at its default of 0 — not added at all for now. Economic retirement is a real future
option (revisit in a later, more targeted study), but not for this initial pass.

- [x] **Fix `RetirementDate`/`CommissionDate` for grouped resources — DONE 2026-07-15.**
      `code/18 existing resource grouping.py`'s `build_grouped()` was hardcoding both fields to
      `None`, silently discarding real EIA-860 data for any resource that went through the
      grouping path (only individual resources — coal, hydro, pumped storage, large thermal —
      kept their real dates). Fixed:
  - `CommissionDate` is now a capacity-weighted average across each group's constituent
    generators (new `_weighted_avg_date()` helper) instead of blank. Coverage went from 42/117
    to 103/121.
  - `RetirementDate` is now propagated when every generator in a group shares the same known/
    unknown retirement status. Four groups mixed retiring and non-retiring generators (e.g.
    `South_PSCO_GasCT_small` = Alamosa's 2 retiring CTs + 7 non-retiring Fountain Valley/Pueblo
    Airport units) — those now split into a `..._retiring` sub-resource and a continuing
    sub-resource so a single `RetirementDate` always applies cleanly. `RetirementDate` coverage
    went from 9/117 to 15/121 (now reflects all 17 EIA-860 announced retirements, not just the
    9 that happened to stay individual).
  - Re-ran the full pipeline (18→22) after the fix; verified no data loss (40 columns intact,
    121 rows, 0 duplicate names, split-group unit counts sum back to originals, all downstream
    O&M/mincap/outage/storage columns fully repopulated for the new split rows).
- [x] **Part B / `code/23 useful life and retirement dates.py` — DONE 2026-07-16.**
      Three-tier hierarchy: EIA-860 announced date → FERC Form 1 Schedule 336 depreciation
      life (named-plant or plant-category, per resource) → NREL ATB Tech Life CRP (renewables/
      storage/hydro) or EIA AEO2026 30-yr cost recovery period (gas), with a 2030-12-01 floor
      for computed dates that land in the past for a still-operating resource. One manual
      policy override (Comanche Unit 3, PUC settlement date). `RetirementDate` coverage:
      **121/121, fully complete.** Also exports
      `data_cleaning/resources/retirement_life_assumptions_table.docx` — a Word table of the
      technology-class life assumptions (doubles as the Phase 3 candidate-resource OpLife
      reference: includes Geothermal/SMR/PV+Battery hybrid rows, inert today, ready when
      needed).
- [x] **Build `24 build resource import template.py` — DONE 2026-07-16.** Writes
      `encompass/02_Import_Templates/5_Baseline_Resources.xlsx`, following the pattern in
      `8 build load forecast import template.py`. Three sheets, verified directly against the
      doc's own SPREADSHEET LEGEND text (not assumed from the reference doc, which had one
      error corrected as part of this — see `encompass_parameter_reference.md` §7 note):
  - `Resource` — nearly everything, including `MaxStorage`/`PaybckReq`/`PaybckCap` (these are
    NOT on a separate "Resource Storage" sheet as previously documented; that sheet is only
    for resources needing multiple storage levels, not our case). `HeatMethod` added as a
    constant `"Average"` wherever `AvgHtRate` is populated. `FirmCap` included as an empty
    column, ready for Phase 2.
  - `Resource Unit Dates` — `CommissionDate`/`RetirementDate`/`Units` live here, not on the
    Resource sheet. All 121 resources have a row.
  - `Resource Emission` — wide-to-long melt of `co2/nox/so2_RelRateMWh`, zero-value rows
    omitted. 168 rows (56 resources × 3 emission types).
  - Validated: 121/121 resources round-tripped with matching names, no duplicates, `WasteHeat`
    linkage spot-checked correct (lives on the CT unit pointing at its CA partner, e.g.
    `cherokee__5`/`cherokee__6` → `cherokee__7`, not the reverse).
- [x] **First import attempt — failed, fixed 2026-07-22.** EnCompass crashed
      (`System.IndexOutOfRangeException` in `LookUpTechType`) because `TechType` is a Lookup
      field validated against a predefined Resource Types tree in the database — our internal
      TechType shorthand (`Gas:CC`, `Hydro:Pumped`, etc.) only coincidentally matched
      EnCompass's actual values in one case (`Storage:Battery`). User pulled the real tree
      from EnCompass's Resources panel; added a `TECHTYPE_TO_ENCOMPASS` translation dict to
      Script 24, applied only at export time (internal names unchanged everywhere else in
      Scripts 18-23). Notably, EnCompass files Pumped Storage Hydro under **Storage**, not
      Hydro (`Storage:Pumped Hydro`), differing from our own taxonomy. Full mapping:
      `Coal→Coal:Conventional`, `Gas:CC→Gas/Oil:Combined Cycle`,
      `Gas:CT→Gas/Oil:Combustion Turbine`, `Gas:ST→Gas/Oil:Steam Turbine`,
      `Gas:IC→Gas/Oil:Internal Combustion`, `Hydro→Hydro` (see next item — this entry was
      wrong on the first pass), `Hydro:Pumped→Storage:Pumped Hydro`,
      `Solar:PV→Renewable:Solar PV`, `Wind→Renewable:Wind`,
      `Storage:Battery→Storage:Battery` (unchanged). Re-exported and verified all 121
      resources translate with no unmapped values.
- [x] **Second import attempt — two more errors, fixed 2026-07-22 same day.** Real validation
      errors this time (not a crash), reported for `TechType = "Hydroelectric"` and
      `Emission = CO2/NOx/SO2`, both "name not found."
  - `TechType`: the Resources panel tree *displays* "Hydroelectric" but the actual stored
    lookup value is `"Hydro"` — our original `Hydro→Hydro` identity mapping was already
    correct; the first-pass fix wrongly "corrected" it to `Hydroelectric`. Confirmed (and
    every other mapping independently cross-checked) against an example EnCompass
    `Legend`/`Lookup Values` export from a different database the user found — TechType is a
    system-defined Lookup, so its valid values are the same across databases.
  - `Emission`: a genuinely different root cause from TechType. The same Legend export shows
    `Emission` is its own EnCompass **object type** (like `Resource`/`Area`/`Fuel`), with its
    own one-column (`Name`) import sheet — not a fixed system Lookup. CO2/NOx/SO2 don't exist
    yet as records in the `2026_Colorado` database, so `Resource Emission` rows referencing
    them by name fail until they're created. Added `build_emission_definitions_sheet()` to
    Script 24 — writes a new `Emission` sheet (first in the workbook, so the objects exist
    before anything references them) with one row per distinct emission name actually used.
  - Re-exported and verified: `Hydro` TechType now correct (10 resources), `Emission` sheet
    present with `CO2`/`NOx`/`SO2` rows ahead of `Resource Emission` in sheet order.
- [x] **Import succeeded — 2026-07-22.** `5_Baseline_Resources.xlsx` imported cleanly into the
      `2026_Colorado` EnCompass database. **This closes out Phase 1's core goal**: the existing
      fleet (grouping, heat rates, emissions, O&M, mincap/outages, storage, retirement dates —
      Scripts 18-24) is validated end-to-end against real EnCompass import, not just sitting in
      a CSV.
- [x] **Sequencing decision (2026-07-22): a basic production-cost simulation of the existing
      fleet in isolation is no longer a near-term goal.** Two real gaps surfaced while
      scoping it — `Fuel`/`Fuel Supply` (no fuel price data or `Fuel` linkage exists anywhere
      in the project; blocks meaningful dispatch cost for the whole thermal fleet) and
      `Transmission`/Area Connections between the 6 zones (`1_Topology_Base.xlsx` only has
      `BA`/`Area` sheets, no transfer limits). Both are real blockers, but the user's primary
      use case is capacity expansion and future candidate-portfolio simulation, not validating
      the existing fleet alone — so building Candidate resources next, then Fuel + Transmission
      once *both* existing and candidate needs are known, makes more sense than fixing Fuel/
      Transmission first. See "Shared infrastructure" section below for the reasoning in full.
- [x] **`MinCap` fixed to be resource-total, not per-unit — 2026-08-14.** Surfaced while building
      the PyPSA translation of `colorado_resources.csv`: Script 17 was storing `MinCap` as a
      **per-unit** MW value (`pmin_frac × (MaxCap/Units)`), while every other capacity-like column
      (`MaxCap`, `MaxStorage`, `PaybckCap`, `max_discharge_mw`) is resource-total. Confirmed via a
      full audit of every multi-unit resource, and via the script's own Pass-2 fallback logic
      (`MinCap × Units / MaxCap`), which had to reverse this same per-unit convention internally —
      not just an inference from one example. Fixed Script 17 to store `MinCap` resource-total
      directly (`pmin_frac × MaxCap`); re-ran, verified all 121 resources produce sensible minimum-
      stable-level percentages (thermal mostly 11–58%, Wind/Solar/CSP must-run cases now correctly
      100% instead of a false ~1/`Units` fraction, batteries still 0%).
      **Action needed: `5_Baseline_Resources.xlsx` has been regenerated with the corrected values
      but has not been re-imported into the production `2026_Colorado` EnCompass database** —
      the already-imported database still has the old, understated per-unit `MinCap` values until
      that re-import happens. Diffed the regenerated workbook against a pre-fix snapshot: only
      `MinCap` changed (50 of 121 rows), both other sheets (`Resource Unit Dates`,
      `Resource Emission`) confirmed byte-identical.
- [ ] **HIGH-PRIORITY, confirmed-not-just-flagged: `MaxCap`/`Units` likely inflates every
      multi-unit existing resource's capacity in the production EnCompass import — 2026-08-14.**
      Not a guess: the actual vendor documentation (`encompass/Documentation/extracted_text/9
      Input descriptions.txt`, line 5959 — "Resource >> Resource General >> Capacity inputs >>
      MaxCap") states, verbatim: *"This input sets the daily maximum output for **each unit** of
      a resource."* Script 14 populates `MaxCap` as a resource-*total* sum
      (`summer_mw.sum()` across a group's units), and `encompass/scripts/4` passes the real
      `Units` count through to EnCompass unmodified — so if EnCompass multiplies `MaxCap × Units`
      internally as documented, every multi-unit resource's effective capacity is overstated by a
      factor of `Units` in the already-imported `2026_Colorado` database (e.g. the ~154 MW
      `Denver_PSCO_GasCC_small` group could be computing as ~921 MW internally, 6×).
      **Does not affect PyPSA** — `colorado_resources.csv`'s stored `MaxCap` is the *correct*
      resource-total value, exactly what PyPSA's `p_nom` wants; the mismatch is specific to
      EnCompass's own per-unit import convention, not the underlying data.
      **Likely root cause (user's hypothesis, 2026-08-14, worth taking seriously)**: a conflation
      between two different things that happen to share the name "Units." Script 14's `Units`
      count is "how many real, distinct EIA-860 generator IDs got merged into this one row" —
      e.g. `Denver_PSCO_GasCC_small`'s `Units=6` comes from grouping `GT1; GT2; ST1; UN5; UN6;
      UN7`, genuinely different physical units, not necessarily identical. EnCompass's own
      `Units` field, per its documentation, appears to assume *homogeneous* replication — N
      identical copies of one template (same `MaxCap`, same heat rate, same everything). Those
      aren't the same concept.
      **Two candidate fixes, not yet chosen between** — both narrow, EnCompass-side-only
      (`encompass/scripts/4` at export time), neither touches `colorado_resources.csv`, Script 14,
      or PyPSA:
        1. Divide `MaxCap` by `Units` at export — assumes the grouped units are interchangeable
           enough that an average per-unit figure is meaningful.
        2. Export `Units=1` for every grouped resource instead — sidesteps the per-unit question
           entirely, since grouped resources aren't EnCompass's intended "identical unit" case to
           begin with. Probably the more conceptually honest fix given the root-cause hypothesis
           above, but changes how EnCompass would model outages/commitment for these resources
           (no more per-sub-unit granularity) — a real trade-off to think through, not free.
      **Not implemented — deliberately deferred** (user preference, 2026-08-14): not currently
      working toward an EnCompass run, and the fix can't be verified without checking a known
      multi-unit resource's actual computed capacity in the live database, which only happens
      when EnCompass work resumes. Do not skip this when it does.

---

## Phase 2 — Candidate new-build resources

**Goal:** build `candidate_resources.csv` (Resource sheet) and `candidate_projects.csv`
(Project sheet) for the agreed baseline technology set. **Next up as of 2026-07-22** — moved
ahead of Firm Capacity and Fuel/Transmission per the sequencing decision above.

### Baseline candidate technology set (confirmed)
Solar:PV (UtilityPV), Solar+Storage hybrid (PV-Plus-Battery), Wind (LandbasedWind),
Storage:Battery, Gas:CT, Gas:CC, SMR (Nuclear - Small), Geothermal (Enhanced/Next-gen) —
8 technologies. SMR and Geothermal are included specifically to keep a "clean firm" option
populated in the baseline even if constrained to near-zero (see open questions below) — this
was a deliberate choice to preserve shadow-price information and avoid a structural rebuild
later if economics or policy shift.

### Deferred to future, more targeted technology studies (not in initial scope)
Pumped Storage Hydro, incremental Hydro (non-powered dam / new stream-reach), Coal CCS retrofit,
Gas CC CCS retrofit, Gas CCS new-build. Full rationale for every ATB technology (including these
and the technologies excluded entirely, e.g. Offshore Wind, CSP, Biopower, new Coal, distributed
DER categories) is in `costs/atb/atb_2024_technology_review.md`.

### Design decisions already made
- **Two-object model confirmed**: every candidate is a `Units=0` Resource row + a linked
  Project row (`encompass_parameter_reference.md` §11–12). Full parameter checklist for both
  tables is in §12, split into required-core vs. optional-refinement tiers.
- **Hybrid solar+storage = two paired resources**, not one combined resource:
  - Both Resource rows share the same `Area` (co-location).
  - Battery Resource: `MaxStorage` set, `DependRes` = solar Resource name (forces charging to
    come only from that solar unit), `PaybckDep` = time series controlling what % of charging
    must come from the dependent resource (models the ITC co-location requirement, can step
    down after the safe-harbor period — documented example steps from 100% to 0% at year 6).
  - Optional: `InvertCap` on the solar Resource if modeling DC-coupled inverter clipping.
  - Two Project rows (solar + battery), linked via `DepProject` — mutual dependency (build in
    matching numbers, same year) or one-way (battery capped by cumulative solar built) — see
    open question below.
- **Use ATB `OCC`, not `CAPEX`, for `CapExRate`.** Confirmed by comparing actual values:
  `CAPEX = OCC + GCC + capitalized interest during construction` (verified via the `Interest
  During Construction - Nominal` field, ~6.5–7%, scaled by each tech's assumed construction
  duration — gap is +$41/kW for solar, +$3,021/kW for geothermal). EnCompass computes this same
  layer itself via `CapIntRate`/`AFUDC`/`Construction Profile` on the Project sheet, so using
  ATB's `CAPEX` would double-count construction financing. Seed EnCompass's `CapIntRate` from
  ATB's `Interest During Construction - Nominal` rate if that detail is wanted explicitly.
- **ATB → EnCompass field mapping** (full table with per-technology exceptions in the chat
  history / to be added to `encompass_parameter_reference.md` §13 when this phase starts):
  `OCC`→`CapExRate`, `Fixed O&M`→`FixedRate`, `Variable O&M`→`EnCost`, `Heat Rate` (×1000,
  MMBtu/MWh→Btu/kWh)→`AvgHtRate`, `Debt Fraction`→`DebtRatio`, `Interest Rate Nominal`→
  `DebtRate`, `Rate of Return on Equity Nominal`→`ROE`, `Tax Rate (Federal and State)`→
  `TaxRate`, `CRPyears`→informs `BookLife`. Financing fields live at the ATB `techdetail="*"`
  row (technology-level, not resource-class-level).
  **Exception:** standalone `Utility-Scale Battery Storage` has no financing fields or
  `Variable O&M` in ATB at all — will need to borrow financing assumptions from a paired
  technology (likely Solar, given shared ITC eligibility).
  **Exception:** the PV-Plus-Battery hybrid reports one *combined* `OCC`/`Fixed O&M` for the
  whole package — needs a decision on splitting vs. keeping bundled when building the two
  paired resources (see open questions).

### Open questions to resolve with more careful thought before building the CSVs
- [ ] Geothermal subtype: `NFEGSBinary` vs `DeepEGSBinary` vs Flash variants — binary cycle at
      moderate temperature is the likely fit for CO's resource, but not yet decided.
- [ ] SMR/Geothermal constraint mechanism: literal `MaxCumAdd = 0` (fully locked out, visible
      in shadow prices) vs. a small nonzero cap (e.g. one unit) — both satisfy "populated but
      constrained," just differ in strictness.
- [ ] Hybrid solar+storage: split ATB's combined OCC/Fixed O&M between the two paired resources,
      or keep it bundled on one side (e.g. all on solar, storage carries only its own duration-
      based adder)?
- [ ] `DepProject` pairing strength for hybrids: mutual (strict, always paired) vs. one-way
      (battery capped by cumulative solar, solar can be built alone)?
- [ ] Candidate technology × zone matrix — which zones (Denver, East, Mountain, North, South,
      West) get which candidate technologies, and at what per-unit block size (`MaxCap`)?
- [ ] Fuel-cost treatment for Geothermal/SMR candidates (raised 2026-07-22) — these likely need
      a fundamentally different `Fuel` treatment than Gas/Coal (near-zero commodity cost for
      geothermal; stable, low, non-market-priced fuel for nuclear) rather than no `Fuel` at all.
      Feeds directly into the deferred Fuel/Fuel Supply design (see Shared Infrastructure
      below) — resolving this while scoping candidates should make that design better, not
      just faster.

---

## Shared infrastructure — Fuel & Transmission (after candidates)

**Goal:** build `Fuel`/`Fuel Supply` (fuel objects + prices) and `Transmission`/Area Connections
(zone-to-zone transfer limits) once, informed by the full set of existing **and** candidate
resource needs — deferred until after Phase 2 (Candidates) per the 2026-07-22 sequencing
decision, not before it.

**Why deferred rather than done first:** both are real gaps (confirmed 2026-07-22 while
scoping a first test simulation) — no `Fuel` object, `Fuel Supply` price data, or `Fuel`
Resource-sheet linkage exists anywhere in the project, and `1_Topology_Base.xlsx` has no
Area Connections between the 6 zones. Neither is a hard build-order dependency, though
(`Fuel` is just another Resource-sheet column, like `TechType`, populated whenever it's built —
not an object-existence dependency the way `Emission` was). Scoping candidates first should
make the Fuel design better, not just faster: Geothermal and SMR likely need meaningfully
different fuel-cost treatment than Gas/Coal, and building Fuel only against the existing fleet
risks a structure that doesn't extend cleanly to those two.

- [ ] `Fuel` objects + `Fuel Supply` (price, `$/FUnit`) + `Fuel Delivery Point` as needed.
      Populate the `Fuel` linkage column on the Resource sheet for both existing and candidate
      thermal resources (Script 24's `RESOURCE_SHEET_DIRECT_COLS` doesn't include it yet).
- [ ] Transmission / Area Connections between the 6 zones. Open question: does EnCompass also
      need explicit BA Interchange data (zones span multiple BAs — PSCO, WACM, others) as
      something distinct from zone-level Area Connections, or do Area Connections cover it?
      Not yet investigated.
- [ ] Re-attempt a full production-cost simulation (existing fleet at minimum, candidates once
      Phase 2 is done) once both are in place.

---

## Firm Capacity / accredited capacity methodology — sequencing not yet decided

**Goal (unchanged):** develop the accreditation methodology once, since it's needed for both
the existing fleet (`FirmCap` on Resource sheet, §8) and every candidate technology (§12,
"Resource table — technology-specific"). Doing it here avoids researching it twice.

**Open as of 2026-07-22:** originally sequenced before Candidates (shared infrastructure,
solve once). That reasoning holds just as well *after* scoping candidates — same logic as the
Fuel/Transmission deferral above. Not yet decided whether to slot this before or after Phase 2
(Candidates); asked, not yet answered.

- [ ] Research CO/WECC-relevant capacity accreditation approach — options include ELCC studies
      (declining accreditation curves per §"Declining firm capacity" in
      `6 Power system modeling.pdf`), NREL Cambium/ReEDS capacity credit values, or values
      already filed in a CO utility's own IRP.
- [ ] Decide whether variable resources (wind/solar/storage) use a flat `FirmCap` % or a
      declining-ELCC Operating Constraint (loading-level table, as documented) — the Operating
      Constraint approach is more realistic as build-out increases but is more setup work.
- [ ] Populate `FirmCap` for all 121 existing resources.
- [ ] Carry the same methodology forward into the candidate Resource rows.
