# NREL ATB 2024 — Technology Review for Colorado Candidate Resources

Source: `data_cleaning/resources/costs/atb/raw/atb_2024.csv` (NREL Annual Technology Baseline
2024, `electricity/csv/2024/v3.0.0/ATBe.csv`, already cached locally — used today by
`code/20 om costs.py` for existing-fleet O&M). This review catalogs every technology ATB covers
and gives an initial recommendation on whether each is a realistic candidate new-build
technology for the Colorado model.

## What ATB 2024 provides per technology

For each technology/subtype/year/scenario combination, ATB publishes: `OCC`/`CAPEX` (overnight
capital cost, $/kW), `Fixed O&M` ($/kW-yr), `Variable O&M` ($/MWh), `CF` (capacity factor),
`Heat Rate` (thermal only), `Fuel` cost, and a full financing block — `WACC (Real/Nominal)`,
`Debt Fraction`, `Interest Rate`, `Rate of Return on Equity`, `CRF`, `FCR`, `Tax Rate` — plus a
derived `LCOE`. The financing fields map directly to the EnCompass `Project`-sheet financing
inputs documented in `encompass_parameter_reference.md` §12 (`DebtRatio`↔`Debt Fraction`,
`DebtRate`↔`Interest Rate Nominal`, `ROE`↔`Rate of Return on Equity Nominal`, `TaxRate`↔`Tax
Rate (Federal and State)`), so ATB can seed both the Resource-table cost fields *and* the
Project-table financing fields for candidates.

Each technology is published under three cost/performance trajectories (`scenario`:
Conservative/Moderate/Advanced) and by `techdetail` resource class (wind/solar/geothermal
classes are resource-quality bins, not project sizes) — matching a resource class to Colorado
requires a separate step (NREL's supply-curve/resource-class GIS layers), the same way this
project already built site-specific wind/solar CF shapes in scripts 9–16 rather than relying on
ATB's own class labels.

## Full technology taxonomy and initial recommendation

Existing-fleet TechType column shown where this project already has a matching category in
`colorado_resources.csv`.

| ATB Technology | Subtypes (techdetail) | Existing TechType | Recommendation | Rationale |
|---|---|---|---|---|
| **UtilityPV** | Class 1–10 (resource quality) | `Solar:PV` | **Include — core candidate** | Already the model's dominant solar category; CF shapes already built (scripts 9–16) |
| **Utility-Scale PV-Plus-Battery** | Class 1–10 | — | **Include — core candidate** | Matches current CO utility procurement trend (Xcel RFPs favor hybrid); fits EnCompass's documented hybrid `DepProject` pairing pattern directly |
| **LandbasedWind** | Class 1–10 (wind speed) | `Wind` | **Include — core candidate** | Already modeled; East zone has strong existing wind buildout and site data (see wind-points memory) |
| **Utility-Scale Battery Storage** | 2/4/6/8/10-hr duration | `Storage:Battery` | **Include — core candidate** | Already modeled; ATB now covers up to 10-hr duration, useful range for standalone storage sizing |
| **NaturalGas_FE** — CT (F-Frame) | — | `Gas:CT` | **Include — core candidate** | Direct match to existing TechType; realistic near-term buildable peaker |
| **NaturalGas_FE** — CC (1-on-1 / 2-on-1, F/H-Frame, no CCS) | 6 configs | `Gas:CC` | **Include — core candidate** | Direct match to existing TechType |
| **Pumped Storage Hydropower** | 19 national resource classes | `Hydro:Pumped` | **Include, selectively** | CO has real PSH siting interest and mountainous topography suited to closed-loop PSH; NREL's national PSH resource assessment (source of these classes) does include CO sites — but treat as a capped/limited candidate, not open-ended, given permitting timelines |
| **Hydropower** | NPD1–8 (non-powered dam), NSD1–4 (new stream-reach) | `Hydro` | **Include, narrowly** | Matches the ORNL hydro resource assessment already cited for existing-fleet O&M (see O&M memory); genuine new-hydro potential in CO is small and site-specific — model as a tightly capped candidate (`MaxCumAdd`), not a general-purpose build option |
| **Nuclear — Small (SMR)** | — | — | **Watch / scenario-only** | No CO utility experience, no committed projects; ATB costs are still first-of-a-kind/speculative. Worth keeping as an optional long-horizon (2040+) sensitivity technology, not baseline |
| **Nuclear — Large** | — | — | **Exclude** | Lead times and cost risk make this infeasible within a typical CO IRP planning horizon; no in-state precedent |
| **Geothermal — Next-gen/Enhanced (NFEGS, DeepEGS)** | Binary/Flash | — | **Watch / scenario-only** | CO has real subsurface heat-flow potential (Rio Grande Rift corridor) and EGS is commercializing (Fervo-style projects) elsewhere, but no CO project exists yet and ATB costs for this subtype remain immature |
| **Geothermal — Conventional Hydrothermal** | Binary/Flash | — | **Exclude** | No known commercial-grade hydrothermal reservoirs in CO at utility scale (existing CO geothermal sites like Pagosa Springs / Mount Princeton are low-temperature, direct-use only) |
| **CSP** | Class 2/3/8 (DNI resource quality) | — | **Exclude for initial model** | CO's DNI (best in San Luis Valley) is well below the SW desert sites that make CSP economic; CSP is presently cost-dominated by PV+storage almost everywhere including CO |
| **Biopower — Dedicated** | — | — | **Exclude / low priority** | CO is not a strong biomass-supply state (semi-arid, limited forestry-residue/ag-residue feedstock relative to SE/Midwest); ATB dedicated-biomass costs are high. Could reconsider narrowly for beetle-kill forest biomass if a specific project surfaces, but not a baseline candidate |
| **Coal_FE (new coal, incl. CCS/IGCC variants)** | 5 variants | `Coal` (existing only) | **Exclude** | Inconsistent with CO's statutory emissions-reduction trajectory (SB19-236/HB19-1261) and Xcel's Clean Energy Plan; all existing coal in this model already carries known retirement dates. No realistic new-build case |
| **Coal_Retrofits (CCS retrofit of existing coal)** | 90%/95% CCS | — | **Exclude from baseline; keep for scenario use** | Only relevant if a specific decarbonization-sensitivity run wants to test retrofitting an existing unit (e.g. Comanche) instead of retiring it — document but don't include by default |
| **NaturalGas_FE — CCS variants (95%/97%)** | 6 configs | — | **Exclude from baseline; keep for scenario use** | Not standard CO utility practice yet; large cost premium. Useful as an optional decarbonization-pathway technology, not a baseline candidate |
| **NaturalGas_FE — Fuel Cell (w/ and w/o CCS)** | 2 configs | — | **Exclude** | Niche, expensive, not a technology CO utilities procure via IRP at grid scale |
| **NaturalGas_Retrofits (CCS retrofit of existing CC)** | 4 configs | — | **Exclude from baseline; keep for scenario use** | Same logic as Coal_Retrofits — relevant only for an explicit CCS-retrofit sensitivity case, would use EnCompass's "combination project" pattern (retire existing unit's config, add retrofit resource) |
| **CommPV / ResPV** | Class 1–10 | — | **Exclude from supply-side candidates** | Behind-the-meter/distributed — a DER adoption question for the load forecast, not a utility-scale capacity-expansion candidate in this model |
| **DistributedWind** | Residential/Commercial/Midsize/Large scale, Class 1–10 | — | **Exclude from supply-side candidates** | Same reasoning as CommPV/ResPV — distributed, not utility supply-side |
| **Commercial / Residential Battery Storage** | 1–8-hr, 5kW/20kWh | — | **Exclude from supply-side candidates** | Behind-the-meter storage; a DER/load-shape question, not a capacity-expansion candidate |
| **OffShoreWind** | Class 1–14 | — | **Exclude** | Colorado is landlocked — not physically applicable |

## Summary: proposed initial candidate technology set

**Core candidates (include now):**
`Solar:PV` (UtilityPV), `Solar:PV+Storage` hybrid, `Wind` (LandbasedWind), `Storage:Battery`
(Utility-Scale), `Gas:CT`, `Gas:CC`

**Limited/capped candidates (include with tight build constraints):**
`Hydro:Pumped` (PSH), `Hydro` (incremental — NPD/NSD)

**Watch list (document now, activate only for a specific sensitivity/scenario run):**
Small Modular Reactor, Enhanced/Next-gen Geothermal, Coal CCS retrofit, Gas CC CCS retrofit,
Gas CCS new-build

**Excluded (not physically or economically realistic for this study):**
Offshore Wind, CSP, Biopower, new Coal, Gas Fuel Cell, all distributed/behind-the-meter
categories (CommPV, ResPV, DistributedWind, Commercial/Residential Battery Storage), Large
Nuclear, conventional Hydrothermal Geothermal
