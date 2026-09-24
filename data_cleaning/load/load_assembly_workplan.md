# Zone Hourly Load Assembly — Work Plan

Living plan for a new `data_cleaning/_scripts/` script that combines existing normalized load
outputs into absolute hourly MW. Mirrors `data_cleaning/resources/resource_planning_workplan.md`
in style. Split out (2026-08-14) from the PyPSA build plan (`pypsa/Documentation/build_plan.md`)
once it became clear this is model-agnostic data prep, not PyPSA-specific glue — see "Why this is
a data_cleaning script" below.

Status as of 2026-08-14. **Complete.** Script 27 built and verified —
`data_cleaning/load/zone_sector_hourly_load_mw_2025.csv` produced (8760 rows, 24 columns).
EnCompass's `2 build load forecast import template.py` refactored to consume it, with a
regression check confirming zero change to already-imported production values.

---

## Goal

Turn three already-existing, deliberately decomposed `data_cleaning/load/` outputs — hourly
shape, base-year sector energy, and annual growth index — into one new output: absolute hourly MW
load for the 2025 base year, at both the zone-sector and zone-aggregate level. This becomes a
shared input for both the EnCompass and PyPSA model builds (and any future platform).

## Why this is a data_cleaning script, not platform-specific glue

Originally planned as PyPSA-side work, reasoning from `encompass/scripts/2 build load forecast
import template.py` as precedent for keeping this kind of thing platform-side. That precedent
didn't hold up under scrutiny: reading both of EnCompass's relevant scripts side by side showed
they aren't doing the same kind of thing.

- `encompass/scripts/3 build renewable cf shapes import template.py` — pure formatting (column
  renaming to EnCompass's time-series names, ×100 unit conversion to percent). No real
  computation. Correctly platform-specific — there's nothing to centralize.
- `encompass/scripts/2 build load forecast import template.py` (lines ~90–216) — does real,
  reusable computation: blends `load_shapes_zone_sector_2018.csv`'s Residential/Commercial/
  Industrial hourly shapes (fraction-of-annual-energy, by zone × sector) by each sector's share of
  `zone_sector_ehat_CO_2024.csv`'s zone-sector annual energy (MWh), scaled to the 2025 base year
  via `I_zt_load_forecast_indices_CO_through_2050.csv`'s `net_demand_forecast_mwh_idx`. Nothing
  about that math is EnCompass-specific — only the output packaging (Interval:1-24 columns,
  TimeSeries sheets) is. It's currently duplicated inline inside the EnCompass script only because
  EnCompass was built before PyPSA was in scope, not because of a deliberate choice to keep it
  platform-side. PyPSA would otherwise re-derive the identical numbers a second time.

This is exactly the kind of "normalize once, consume from many platforms" step the rest of
`data_cleaning/_scripts` already does — shapes, base energy, and growth indices are already kept
as separate, independent CSVs for this reason. The combination into absolute MW just hadn't been
centralized yet.

**Lesson for future "does this belong in data_cleaning or a platform folder" questions:** check
whether the specific *computation* is reusable, not just whether a similarly-named step exists in
another platform's folder. A platform script that "does the same thing" might be doing real shared
math (centralize it) or pure format-specific packaging (leave it be) — those look similar from the
outside but aren't.

## Design decisions

**Output granularity — both zone-sector and zone-aggregate, one file.** Sector-level costs nothing
extra (the same computation produces both as intermediate and final values) and stays
forward-compatible with sector-differentiated load growth — e.g. electrification scenarios, a
plausible future need for a decarbonization-pathways study — even though today's growth index is
zone-level only with no sector breakdown, meaning blend-then-scale and scale-then-blend are
mathematically identical *today*. Nothing is lost by centralizing the blend now.

**Scope — 2025 base year only, not the full 2025–2050 projection.** Scaling to any other year is a
one-line scalar multiply by that year's zone growth index — trivial enough to leave to each
consuming platform rather than materializing ~1.3M rows (26 years × 6 zones × 8760 hours) that
would just be the same base series times a scalar.

**New script, not a modification of Scripts 2–4.** `energy baseline allocation.py` (Script 2),
`load forecast.py` (Script 3), and `load shapes.py` (Script 4) — whichever produces which of the
three source files — remain independently useful in decomposed form; EnCompass's own pipeline
already consumes them separately and works correctly. A new downstream combination script matches
the existing pattern of small, single-purpose, additive scripts (e.g. Script 12 `calibrate solar
wind profiles.py` is already a downstream combination step over Scripts 9–11's outputs) without
disturbing already-working upstream scripts.

## Plan

- [x] **New script**: `data_cleaning/_scripts/27 zone hourly load assembly.py` (next sequential
      number after `26 co2 policy target.py`, following this project's flat-numbering convention
      — Scripts 23–26 were appended the same way rather than interleaved near related scripts).
      Numbering decision confirmed 2026-08-14 after considering and rejecting both a
      topically-adjacent renumber and a full category-tag pipeline reorg (real precedent found for
      why renumbering is risky: `resource_planning_workplan.md` already has stale script-number
      references — `code/18`, `code/23` — from a past reorg that was never fully cleaned up).
- [x] **Reads**:
  - `data_cleaning/load/load_shapes_zone_sector_2018.csv` — hourly shape (`hour` 1–8760, fraction
    of annual energy), columns `{Zone}_Res`, `{Zone}_Com` per zone, plus one shared `Industrial`
    column.
  - `data_cleaning/load/zone_sector_ehat_CO_2024.csv` — base-year zone-sector annual energy (MWh),
    columns `zone, Residential, Commercial, Industry`.
  - `data_cleaning/load/I_zt_load_forecast_indices_CO_through_2050.csv` — used only to pull each
    zone's `net_demand_forecast_mwh_idx` at `forecast_year == 2025`, to align the 2024 raw energy
    data to the formal 2025 base year (mirrors exactly what the EnCompass script already does).
- [x] **Computation** (mirrors `encompass/scripts/2 build load forecast import template.py` lines
      ~160–206, minus the EnCompass-specific packaging):
  1. For each zone: `energy_2025_mwh[sector] = zone_sector_ehat[sector] * net_demand_forecast_mwh_idx(zone, 2025)`.
  2. For each zone-sector: `hourly_mw[hour] = shape[hour] * energy_2025_mwh[sector]` (shape
     fraction × annual MWh → hourly MW, since each interval is 1 hour).
  3. Zone aggregate: `hourly_mw[zone] = sum over sectors of hourly_mw[zone, sector]`.
- [x] **Writes**: `data_cleaning/load/zone_sector_hourly_load_mw_2025.csv` — `hour` (1–8760) index,
      columns `{Zone}_Res_mw`, `{Zone}_Com_mw`, `{Zone}_Ind_mw` for all 6 zones (18 columns) plus
      `{Zone}_mw` aggregate columns (6 columns) — 24 value columns total, matching the wide-CSV
      convention already used by e.g. `solar_cf_calibrated.csv`.
- [x] Follows existing script conventions: `find_project_root()` from repo-root `utils.py` for
      paths, plain pandas, no new dependencies.

## Verification

- [x] Row count: 8760. Confirmed (also asserted in-script).
- [x] For each zone, `{Zone}_mw` equals the sum of its `_Res_mw`/`_Com_mw`/`_Ind_mw` columns.
      Asserted in-script (`verify()`, max diff < 1e-9 for every zone) — passed.
- [x] Annual sum of each zone's aggregate `{Zone}_mw` column (MWh) matches
      `zone_sector_ehat_CO_2024.csv`'s total energy for that zone, scaled by the 2025 growth
      index. Asserted in-script (`verify()`, rel. error < 1e-6 for every zone) — passed. Sum
      across all zones ≈ 56.8 TWh/year, a plausible magnitude for Colorado's total annual
      electricity consumption.
- [x] Spot-checked Denver/East/Mountain/North/South/West at hours 1, 100, 4380, 8760 against
      `encompass/02_Import_Templates/2_Load_Shapes.xlsx`'s already-produced, already-imported
      values (script `2 build load forecast import template.py`'s output) — matched to
      floating-point precision (differences ~1e-16) in all 24 checks, confirming the two
      computations are the same math, not just similar.

## Downstream consumers

- **PyPSA** (`pypsa/Documentation/build_plan.md`, Milestone 1): reads this file's zone-aggregate
  columns, scales by the target year's growth index, reshapes into `loads_t.p_set`.
- **EnCompass**: `encompass/scripts/2 build load forecast import template.py` — **refactored
  2026-08-14 (done, not deferred).** Removed the blending block (`res_shape * res_weight + ...`,
  the `energy_2025_idx`/`energy_2025_mwh` scaling, and the dead `sector_suffix_map`/
  `shape_source_map` dicts it left behind) and replaced it with a direct read of
  `zone_sector_hourly_load_mw_2025.csv`'s `{zone}_mw` aggregate column. `zone_growth`/`energy_idx`
  scaling to other years (2026-2050) is untouched — that's still genuinely EnCompass-side work,
  analogous to what PyPSA's Milestone 1 does with the same base file.

### Regression safety for the EnCompass refactor — passed

`2_Load_Shapes.xlsx` is already successfully imported into the production `2026_Colorado`
EnCompass database (per `resource_planning_workplan.md`, 2026-07-22) — the refactor needed to not
silently change those already-imported values.

- [x] Snapshotted the pre-refactor `2_Load_Shapes.xlsx` / `3_Load_Forecast_Parameters.xlsx`
      (already on disk from the last real run, before any code changes) to a scratch location.
- [x] Re-ran the refactored script, diffed every sheet of both workbooks (`TimeSeries`,
      `TimeSeriesDatedChanges`, `LoadGroup`) cell-by-cell against the snapshot — **fully identical**
      (within 1e-6 float tolerance; all 2190 + 624 dated-change rows and every TimeSeries/LoadGroup
      row matched). Confirms the refactor is a pure internal simplification, zero behavior change.
- [x] No re-import into EnCompass needed — diff confirmed no change to the values already in
      production.
