# EnCompass Parameter Reference — Colorado 2026 Electric Model

This file documents the EnCompass input parameter names, units, and how they map to
columns in `colorado_resources.csv` (Scripts 18–19 output) and future scripts.

Source: `encompass/Documentation/9 Input descriptions.pdf` (Yes Energy, 2026-03-05, 143 pages)

---

## Column header notation

EnCompass imports from spreadsheets where:
- **Sheet name** = which input spreadsheet tab (Resource, Resource Dispatch, Resource Emission, etc.)
- **Column header** = exact column name EnCompass reads
- Frequency = how often the value can vary (Once = constant, Monthly, Daily, Interval = hourly)

---

## 1. Capacity / Timing (Resource sheet)

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `MaxCap` | MW | — | Daily | Maximum output per unit | `summer_mw` |
| `MinCap` | MW | 0 | Interval | Min generation; if not set, unit is always online and all commitment constraints ignored | Script 21 (TBD) |
| `CommissionDate` | Date | 1/1/1900 | By index | First date of operation for the number of units | `online_year` → Script 2x |
| `RetirementDate` | Date | 12/31/2200 | By index | Last date of operation | `retirement_year` → Script 2x |
| `Units` | count | 1 | By index | Number of identical units; best practice for GTs, hydro turbines, wind, solar | `unit_count` |
| `Area` | Area | — | Once | Every resource must be assigned to a single Area | `zone` |

---

## 2. Fixed O&M (Resource sheet — Costs inputs)

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `FixedRate` | $/kW-yr | 0 | Monthly | Fixed O&M applied to MaxCap; divided by 12 for monthly cost | Script 20 (TBD) |
| `FixedCost` | $000/yr | 0 | Monthly | Per-unit fixed ongoing cost (alternative to FixedRate) | Script 20 (TBD) |

**Note:** Use `FixedRate` ($/kW-yr) when cost data comes from sources like NREL ATB (which
reports in $/kW-yr). EnCompass multiplies `FixedRate × MaxCap / 12` each month.

---

## 3. Variable O&M (Resource sheet — Costs inputs)

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `EnCost` | $/MWh | 0 | Interval | Applied to actual generation; explicitly intended for variable O&M | Script 20 (TBD) |
| `OnlineCost` | $/hr | 0 | Interval | Applied to units online (run-hours based maintenance); only active when MinCap is set | Script 21 (TBD, optional) |

---

## 4. Heat Rate / Dispatch (Resource sheet + Resource Dispatch sheet)

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `AvgHtRate` | Btu/kWh | 0 | By load level, Interval | Average heat rate when `HeatMethod = Average` (default) | `heat_rate_btu_kwh` |
| `HeatMethod` | Average / Incremental / Curve | Average | Once | Selects heat rate interpretation | Constant: "Average" |
| `DispAdder` | $/MWh | 0 | By load level, Interval | Dispatch cost adder on top of fuel cost | Not yet in CSV |
| `HeatCurveA` | mmBtu/hr | 0 | Interval | Fixed heat input (only when `HeatMethod = Curve`) | Not used |
| `HeatCurveB` | mmBtu/MWh | 0 | Interval | Linear heat curve component | Not used |
| `WasteHeat` | Resource | — | Once | Links CT to its steam turbine (CA); CT runs at simple-cycle heat rate | `waste_heat_resource` |
| `WHBypass` | Yes / Outage Only / No | Yes | Once | Whether CT can run simple-cycle if CA is offline | `waste_heat_bypass` |

**Our mapping:** `heat_rate_btu_kwh` → `AvgHtRate` (same units, Btu/kWh, no conversion needed)

---

## 5. Emission Rates (Resource Emission sheet)

EnCompass uses one row per emission type (CO2, NOx, SO2) per resource.

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `Emission` | Emission | — | By index | Which emission type (CO2, NOx, SO2) | Row identifier |
| `RelRateMWh` | lb/MWh | 0 | By emission, Interval | Linear release rate per MWh of generation | `co2_lbs_mwh` / `nox_lbs_mwh` / `so2_lbs_mwh` |
| `RelRate` | lb/mmBtu | 0 | By emission, Interval | Release rate per heat input (alternative to RelRateMWh) | Not used (we use lb/MWh) |
| `RemoveRate` | % | 0 | By emission, Interval | Emission removal (scrubbers, baghouses) | Not yet in CSV |
| `RelRateA` | lb/hr | 0 | By emission, Interval | Fixed release component (intercept) | Not used |

**Our mapping:** Each of `co2_RelRateMWh`, `nox_RelRateMWh`, `so2_RelRateMWh` → `RelRateMWh` on a
separate emission row. No unit conversion needed (our units are already lb/MWh).

**Format note — wide-to-long reshape required at import time:**
`colorado_resources.csv` stores emissions in **wide format** (one row per resource, three
separate columns). EnCompass requires **long format** (one row per resource × emission
combination, with a separate `Emission` index column). The import-builder script must melt
before writing to the EnCompass spreadsheet:

```
colorado_resources.csv (wide)          EnCompass Resource Emission sheet (long)
---------------------------------      -----------------------------------------
Name          co2_  nox_  so2_         Resource        Emission   RelRateMWh
              RelR  RelR  RelR
cherokee__1   2110  5.0   13.0   →     cherokee__1     CO2        2110
                                       cherokee__1     NOx        5.0
                                       cherokee__1     SO2        13.0
```

Zero-emission resources (renewables, CA steam turbines) should be omitted from the
emission sheet entirely — do not write rows with RelRateMWh = 0.

**Emission type convention (from documentation):**
- CO2 — documentation notes this is "usually specified for each fuel" (fuel-level `RelRate`
  in lb/mmBtu). Using resource-level `RelRateMWh` instead is valid and more precise since
  our values come from eGRID plant-level data that already reflects actual controls.
- NOx — documentation notes this is "usually specified for each resource" (resource-level).
  Our approach matches this convention.
- SO2 — documentation notes either fuel-level or resource-level is acceptable. We use
  resource-level for consistency.

---

## 6. Outages (Resource sheet — Outages inputs)

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `FOR` | % | 0 | Daily | Forced outage rate (daily complete failure probability) | Script 21 (TBD) |
| `FORLength` | Days | 1 | Daily | Expected length of a forced outage | Script 21 (TBD) |
| `MOR` | % | 0 | Daily | Maintenance outage rate (capacity deration, not a binary outage) | Script 21 (TBD) |
| `NumMaint` | Units | 0 | — | Scheduled outage units | Script 21 (TBD) |
| `MaintShift` | Days | 0 | — | Allowable maintenance shift | Script 21 (TBD) |

**Source for Script 21:** EIA-923 historical forced outage data, or NERC GADS averages by
tech type. WECC planning assumptions documents also publish FOR by tech class.

---

## 7. Storage (Resource sheet)

**Correction (2026-07-16, verified directly against doc text while building Script 24):**
all storage columns below live on the **Resource** sheet itself, not a separate "Resource
Storage" sheet as previously stated here. The actual "Resource Storage" sheet only applies
when a resource needs *multiple* storage levels (`StorDepPct`/`StorDepPen` with an
`ItemIndex` per level) — none of our 15 storage resources need that; each has a single
storage level, so `MaxStorage`, `PaybckReq`, and `PaybckCap` are just ordinary columns on
the main Resource sheet alongside everything else.

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `MaxStorage` | MWh | 999,999 | Interval | Maximum stored energy per unit | `storage_mwh` (TBD) |
| `PaybckReq` | % | 0 | Interval | Energy required to recharge; 100/round-trip-efficiency (e.g., 125% for 80% RT eff.) | 125% for Li-ion |
| `PaybckCap` | MW | 999,999 | Interval | Max charging power per unit; defaults to MaxCap if not set | `charge_mw` (TBD) |
| `MinStorage` | MWh | 0 | Interval | Minimum stored energy (e.g., for reliability reserve) | Not yet in CSV |
| `StoreLoss` | %/hour | 0 | Interval | Standing loss rate (self-discharge) | Not yet in CSV |
| `PaybckCost` | $/MWh | 0 | Interval | Cost applied to charging energy | Not yet in CSV |

---

## 8. Capacity Market (Resource sheet — Capacity inputs)

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `FirmCap` | % | 100 | Daily | Firm capacity contribution for capacity adequacy (% of MaxCap/InvertCap) | `accredited_capacity_pct` in colorado_resources.csv (dispatchable only as of Script 23; verified against `9 Input descriptions.txt` — this entry previously wrongly said MW, corrected 2026-08-05) |
| `MaxRetire` | Units | 0 | Annual | Units available for economic retirement optimization | 1 for existing fleet |

---

## 9. Renewables — Capacity Factor Profile

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `NetGenLim` | % | 100 | Interval | Capacity factor limit per hour (wind/solar shape) | Script 2x (CF shapes) |
| `MinOnline` | Units | ≥1 | — | Forces must-run; set = Units for non-dispatchable renewables | Constant for wind/solar |

**Note:** Wind and solar are configured with `MinCap = MaxCap`, `MinOnline = Units`, and an
hourly `NetGenLim` time series derived from historical capacity factor shapes.

---

## 10. Production Tax Credits

| EnCompass Column | Units | Default | Frequency | Description | CSV Source |
|-----------------|-------|---------|-----------|-------------|------------|
| `PTC` | $/MWh | 0 | Interval | IRA PTC; applied to delivered generation in first 10 years; grossed up by tax rate | Script 2x (TBD) |

---

## colorado_resources.csv Column Mapping Summary

| CSV Column | EnCompass Parameter | Sheet | Notes |
|------------|--------------------|----|-------|
| `Area` | `Area` | Resource | Direct mapping |
| `Name` | `Name` | Resource | Direct mapping |
| `TechType` | `TechType` | Resource | Lookup table mapping needed |
| `MaxCap` | `MaxCap` | Resource | Units: MW; direct mapping |
| `Units` | `Units` | Resource Unit Dates | Direct mapping |
| `CommissionDate` | `CommissionDate` | Resource Unit Dates | Direct mapping |
| `RetirementDate` | `RetirementDate` | Resource Unit Dates | Direct mapping |
| `WasteHeat` | `WasteHeat` | Resource | Direct mapping |
| `WHBypass` | `WHBypass` | Resource | Direct mapping |
| `AvgHtRate` | `AvgHtRate` | Resource (Dispatch) | Direct mapping; same units (Btu/kWh) |
| `NetGenLim` | `NetGenLim` | Resource | CF shape label → hourly time series at import |
| `MaxStorage` | `MaxStorage` | Resource | Direct mapping; units: MWh |
| `PaybckCap` | `PaybckCap` | Resource | Direct mapping; units: MW |
| `co2_RelRateMWh` | `RelRateMWh` where `Emission`=CO2 | Resource Emission | **Reshape required** — melt wide→long at import |
| `nox_RelRateMWh` | `RelRateMWh` where `Emission`=NOx | Resource Emission | **Reshape required** — melt wide→long at import |
| `so2_RelRateMWh` | `RelRateMWh` where `Emission`=SO2 | Resource Emission | **Reshape required** — melt wide→long at import |
| *(Script 20)* | `FixedRate` | Resource | $/kW-yr fixed O&M |
| *(Script 20)* | `EnCost` | Resource | $/MWh variable O&M |
| *(Script 21)* | `FOR` | Resource | % forced outage rate |
| *(Script 21)* | `FORLength` | Resource | Days per outage event |
| *(Script 21)* | `MOR` | Resource | % maintenance outage rate |
| *(Script 2x)* | `PaybckReq` | Resource | % = 100/round-trip-efficiency |

---

## 11. Candidate / New-Build Resources — the `Project` sheet (Expansion)

Source: `encompass/Documentation/9 Input descriptions.pdf`, "Expansion >> Projects inputs" and
"Expansion >> Project Constraint inputs" (pp. 125–143); `6 Power system modeling.pdf`,
"Expansion" narrative (pp. 44–47). Full plain-text extraction of every doc PDF is saved at
`encompass/Documentation/extracted_text/*.txt` (via `pdftotext -layout`) for future grep-based
lookups — regenerate if the PDFs are ever updated.

**Key finding: candidate resources are not Resource-sheet rows. They are a second, linked
object called a `Project`, on entirely separate spreadsheet tabs (`Project`, `Project Profile`,
`Project Areas`, `ProjConstr`).** A candidate resource is always *two* records working together:

1. **A `Resource` row** (same sheet `colorado_resources.csv` feeds today) describing the
   technology's physical/technical characteristics — `TechType`, `MaxCap` (per-unit size),
   `AvgHtRate`, emission rates, `FixedRate`/`EnCost`, storage params, etc. — but with
   **`Units = 0`** (explicitly, since the default is 1) because the capacity doesn't exist yet.
   No `CommissionDate`/`RetirementDate` is set on this row; EnCompass assigns
   `CommissionDate = Jan 1` of whichever year the optimizer actually selects the project.
2. **A `Project` row** on the `Project` sheet that references that Resource by name (column
   `Resource`) and adds everything the Resource sheet has no columns for: capital cost,
   financing, build timing, and build limits.

This mirrors a build pattern already visible in `colorado_resources.csv` today for
`status_category = proposed` rows (e.g. `sundance_co_SolarPV_proposed`) — **but those are not
the same thing as capacity-expansion candidates.** `proposed` rows are specific,
EIA-860-identified interconnection-queue projects (real `plant_codes`/`generator_ids`, a real
name and location) added the same way as existing plants. Capacity-expansion candidates are
*generic, hypothetical* technology options (e.g. "generic 100 MW solar block in the North zone")
that the optimizer decides whether/when/how much to build — that decision-making is exactly what
the `Project` sheet's financing and limit inputs exist to drive. Don't conflate the two.

### 11a. `Project` sheet — core identity / linkage

| Column | Units | Default | Frequency | Description |
|---|---|---|---|---|
| `Name` | string | — | — | Project name |
| `Resource` | Resource | — | Once | The Resource this project builds. Set `Units=0` on that Resource row for greenfield/new-tech. |
| `RetireRes` | Resource | — | Once | Optional: a Resource to retire when this project is selected (pairs a build with a retirement) |
| `NumRetire` | Units | 1 | Once | Number of units of `RetireRes` retired per selection |
| `AddUnits` | Integer | 0 (→1 if unset) | Once | Number of units of `Resource` added per project selection |
| `AreaConn` | Area Connection | — | Once | Alternative to `Resource`: adds a new transmission interconnection instead of/with generation |
| `DelPoint` | Fuel Delivery Point | — | Once | Alternative object type: lets expansion add firm fuel contracts/storage |
| `Region` | Region | — | Once | If set instead of a single `Area`, EnCompass copies the resource into every Area in the region and picks the best one. Note: Firm Capacity Operating Constraints only apply within the Resource's own Area, not to Region-copied resources. |
| `DepProject` | Project | — | Once | Dependent Project — forces paired/ordered builds (e.g. battery hybrid must pair with its solar/wind project). Mutual dependency if set on both projects. |

### 11b. `Project` sheet — timing / build profile

| Column | Units | Default | Frequency | Description |
|---|---|---|---|---|
| `BegYear` | Year | 0 | Once | "Project Beginning Year" — anchors Year-1 for sliding direct-cost time series; only needed for costs input directly (not `CapEx`/`CapExRate`) |
| `BookLife` | Years | 0 | Once | Financing term; required whenever `CapEx`/`CapExRate` is used |
| `OpLife` | Years | 0 | Once | In-service duration; auto-extended to `BookLife` if shorter |
| `TaxLife` | Years | — | Once | If < `BookLife`, triggers MACRS accelerated tax depreciation |
| `PartialYr` | Year | 9999 | Once | Lets a "generic" project take only the capacity still needed in later optimization years (runtime optimization) |
| `UnitProf` | Units (ratio) | 0 | Monthly, **relative year** | Construction/build-out profile — index 1 = first year project is selected, regardless of actual calendar year. Used for mid-year in-service dates, phased multi-unit rollout, or year-over-year capacity decline (e.g. solar degradation) |

### 11c. `Project` sheet — build limits

| Column | Units | Default | Frequency | Description |
|---|---|---|---|---|
| `MaxIncAdd` | Projects | 999,999 | Annual | Max additions of this project per year |
| `MaxCumAdd` | Projects | 999,999 | Annual | Max cumulative (active) additions |

Companion `Project Areas` sheet sets **`MinIncAdd`** (Minimum Active Projects) per Area/Node —
used to *force* committed builds even when expansion optimization is off; overrides max limits
if needed.

### 11d. `Project` sheet — financing (all "Annual" frequency Time Series)

| Column | Units | Default | Description |
|---|---|---|---|
| `RateBase` | lookup | Unregulated | Financing method: `Unregulated` (ROE-driven IRR), `Rate Base`, or `Rate Base Average` |
| `CapEx` | $000 | 0 | Total overnight capital cost per project addition |
| `CapExRate` | $/kW | 0 | Same, on a $/kW basis (uses Jan-1-of-install-year capacity); added to `CapEx` |
| `DebtRatio` | % | 0 | % of CapEx financed with debt |
| `DebtRate` | % | 0 | Long-term debt interest rate |
| `ROE` | % | 0 | Target after-tax return on equity (Unregulated financing) |
| `TIER` | ratio | 1 | Alternative to ROE for debt-heavy public power |
| `TaxRate` | % | 0 | Composite income tax rate; falls back to Area-level input if unset |
| `ITC` | % | 0 | Investment tax credit % of capital investment |
| `RegITCOpt` | lookup | Amortized in Rate Base | How ITC reduces revenue requirement under Rate Base financing |
| `AFUDC` | % | 0 | Allowance for funds used during construction (Rate Base financing) |
| `CapIntRate` | % | 0 | Capitalized interest rate (Unregulated financing); defaults to `DebtRate` |
| `CWIP` | % | 0 | % of construction cost included in rate base pre-in-service |
| `Insurance` / `PropTax` | % | 0 | Applied to `TxInsBasis` (Original or Depreciated book value) |
| `DecommRate` | % | 0 | % of book value set aside annually for decommissioning |
| `TxInsBasis` | lookup | Original | Basis for Insurance/PropTax: constant (Original) vs declining (Depreciated) |

Direct-cost overrides (all optional, all "slide" relative to `BegYear` if set): `OtherCosts`,
`AddTaxCred`, `ActualCWIP`, `ActAFUDC`, `BookDep`, `TaxDep`, `RtBaseAdj`, `BegDefTax`.

### 11e. `ProjConstr` sheet — cross-project constraints

Groups multiple `Project` rows with a per-project `Factor` (default 1) into one linear
constraint: `MaxIncAdd`/`MaxCumAdd`/`MinProject` bound the weighted sum. Used for mutual
exclusivity ("build at most one of A, B"), forced pairing ("A ≤ B"), or "build at least one from
this group" requirements — e.g. capping total candidate solar across zones sharing a
transmission constraint.

### 11f. Practical pattern: hybrid (paired) resources

Documented worked example (`6 Power system modeling.pdf`, "Battery as a Project/Resource
Candidate"): define **two** `Project` rows — one for the generating resource (solar/wind), one
for the battery — and set `DepProject` so they must be added in matching numbers in the same
year (mutual dependency), or so the battery can only be added up to the cumulative count of the
paired generation project (one-way dependency).

### Recommendation: do not add candidate resources to `colorado_resources.csv` as-is

`colorado_resources.csv` today is structured one row per **real, identifiable** generator
(EIA-860 `plant_codes`/`generator_ids`, sourced `heat_rate_source`/`emission_source`/`om_source`
provenance columns, etc.) and only ever feeds the `Resource` sheet. Candidate new-build
resources need two things this file has no room for:

1. A `Resource`-sheet row *without* any real plant identity (no `plant_codes`, no
   `CommissionDate`) — mixing that into a table whose schema assumes real-plant provenance
   metadata would leave ~10 columns null for every candidate row and blur the very useful
   `status_category`/`filter_source` provenance tracking that exists today.
2. An entire second object (the `Project` sheet, section 11a–11d above) that has **no analog
   columns in `colorado_resources.csv` at all** — capital cost, financing, and build-limit
   inputs are structurally absent from the existing schema, so a second file is required
   regardless of what's done with the Resource-sheet side.

**Proposed structure** (mirrors EnCompass's own two-object model):

- `candidate_resources.csv` — one row per generic technology × zone (e.g.
  `Generic_Solar_North`, `Generic_4hrBattery_Denver`), reusing the physical/technical columns
  from `colorado_resources.csv` (`TechType`, `MaxCap`, `AvgHtRate`, emissions, `FixedRate`,
  `EnCost`, storage params) with `Units=0` and no plant-identity columns, feeding the `Resource`
  sheet.
- `candidate_projects.csv` — one row per candidate project, referencing the Resource names
  above via `Resource`, carrying `AddUnits`, `Region`/`Area`, `CapEx`/`CapExRate`, financing
  (`BookLife`, `OpLife`, `DebtRatio`, `ROE`/`TIER`, `ITC`, etc.), and `MaxIncAdd`/`MaxCumAdd`
  build limits, feeding the `Project` sheet.
- Optionally `candidate_project_constraints.csv` for cross-project limits (section 11e) if
  zones share transmission-constrained build caps or technologies need mutual exclusivity.

---

## 12. Candidate Resource Build Checklist — full parameter list, Resource vs Project

Consolidated list of every parameter needed to define a candidate new-build resource, pulled
from sections 1–11 above. **Table** column shows which spreadsheet the parameter lives on —
this is the actionable column mapping for building `candidate_resources.csv` (→ `Resource`
sheet) and `candidate_projects.csv` (→ `Project` sheet).

### Resource table — core (every candidate needs these)

| Parameter | Table | Units | Required? | Notes |
|---|---|---|---|---|
| `Name` | Resource | string | Required | Generic resource name, e.g. `Generic_Solar_North` |
| `Area` | Resource | Area | Required | Zone assignment |
| `TechType` | Resource | lookup | Required | Technology class |
| `Units` | Resource | count | Required | **Explicitly 0** — capacity doesn't exist yet |
| `MaxCap` | Resource | MW | Required | Per-unit block size (the increment the optimizer builds in) |
| `FixedRate` | Resource | $/kW-yr | Required | Fixed O&M |
| `EnCost` | Resource | $/MWh | Required | Variable O&M |
| `CommissionDate` | Resource | Date | **Do not set** | Project assigns this dynamically when selected |
| `RetirementDate` | Resource | Date | **Do not set** | Derived from Project's `OpLife` instead |

### Resource table — technology-specific

| Parameter | Table | Units | Required? | Notes |
|---|---|---|---|---|
| `AvgHtRate` | Resource | Btu/kWh | Thermal only | |
| `HeatMethod` | Resource | lookup | Thermal only | Constant `"Average"` |
| `WasteHeat` / `WHBypass` | Resource | Resource / lookup | CC candidates only | Link CT→ST if modeling as separate units |
| `co2_RelRateMWh` / `nox_RelRateMWh` / `so2_RelRateMWh` | Resource | lb/MWh | Thermal only | Omit rows entirely for zero-emission techs (melt to long format) |
| `MinCap` | Resource | MW | Thermal: yes: Renewables: = MaxCap | Min generation / must-run level |
| `FOR` / `FORLength` / `MOR` | Resource | % / days / % | Thermal: yes; Renewables: 0 | Outage rates by tech class (NERC GADS/WECC) |
| `MaxStorage` | Resource | MWh | Storage only | |
| `PaybckReq` | Resource | % | Storage only | 100/round-trip efficiency |
| `PaybckCap` | Resource | MW | Storage only | Charge power limit |
| `MinStorage` / `StoreLoss` / `PaybckCost` | Resource | MWh / %/hr / $/MWh | Storage: optional | |
| `NetGenLim` | Resource | % (time series) | Wind/Solar only | CF shape label |
| `MinOnline` | Resource | Units | Wind/Solar only | = `Units` to force must-run/non-dispatchable |
| `FirmCap` | Resource | % | Recommended, all techs | Capacity value for reserve margin/capacity market; renewables/storage may instead use a Declining Firm Capacity (ELCC) Operating Constraint (§ Power system modeling, "Declining firm capacity") |
| `PTC` | Resource | $/MWh | If IRA-eligible | Wind/solar/storage; applied first 10 yrs |

### Project table — core (every candidate project needs these)

| Parameter | Table | Units | Required? | Notes |
|---|---|---|---|---|
| `Name` | Project | string | Required | Project name |
| `Resource` | Project | Resource | Required | Links to the candidate's Resource row |
| `AddUnits` | Project | count | Required | Units added per selection (defaults to 1 if unset) |
| `Region` or `Area` | Project | Region / Area | Required (one of) | `Region` lets optimizer pick best zone; otherwise Resource's own `Area` governs |
| `CapEx` or `CapExRate` | Project | $000 / $/kW | Required (one of) | Overnight capital cost |
| `BookLife` | Project | Years | Required whenever CapEx set | Financing term |
| `OpLife` | Project | Years | Required | In-service duration; drives derived `RetirementDate` |
| `RateBase` | Project | lookup | Recommended | Default `Unregulated`; set explicitly |
| `DebtRatio` / `DebtRate` | Project | % | Required | Debt financing assumptions |
| `ROE` (or `TIER`) | Project | % (or ratio) | Required (one of) | Return target |
| `TaxRate` | Project | % | Required (or falls back to Area default) | |

### Project table — financing detail (optional, refine as needed)

| Parameter | Table | Units | Notes |
|---|---|---|---|
| `TaxLife` | Project | Years | Triggers MACRS if < `BookLife` |
| `ITC` | Project | % | Investment tax credit |
| `RegITCOpt` | Project | lookup | Only matters for Rate Base financing |
| `AFUDC` / `CapIntRate` | Project | % | Construction financing cost |
| `CWIP` | Project | % | Rate Base financing only |
| `Insurance` / `PropTax` / `TxInsBasis` | Project | % / lookup | |
| `DecommRate` | Project | % | |
| `PartialYr` | Project | Year | Runtime optimization aid, not economics |
| `UnitProf` | Project | ratio (time series) | Phased build-out or degradation profile |

### Project table — build limits & linkage (optional)

| Parameter | Table | Units | Notes |
|---|---|---|---|
| `MaxIncAdd` | Project | Projects | Annual build cap |
| `MaxCumAdd` | Project | Projects | Cumulative build cap |
| `DepProject` | Project | Project | Pairs hybrid builds (e.g. battery ↔ solar) |
| `RetireRes` / `NumRetire` | Project | Resource / count | Only if pairing this build with retirement of a specific existing unit |

### Project Areas table (optional — only if forcing minimum builds)

| Parameter | Table | Units | Notes |
|---|---|---|---|
| `Area` | Project Areas | Area | Defaults to Resource's Area if unset |
| `MinIncAdd` | Project Areas | Projects | Forces committed minimum builds even outside optimization |
| `Node` | Project Areas | Bus/Hub/Resource | Nodal simulations only |

### ProjConstr table (optional — only if cross-project constraints needed)

| Parameter | Table | Units | Notes |
|---|---|---|---|
| `Name` | ProjConstr | string | Constraint group name |
| `MaxIncAdd` / `MaxCumAdd` / `MinProject` | ProjConstr | Projects | Group-level limits |
| `Project` | ProjConstr | Project | Which projects belong to the group |
| `Factor` | ProjConstr | ratio | Per-project weight in the group's linear constraint (default 1) |
