# PyPSA-CO

An open, publicly reproducible, multi-period capacity-expansion model of
Colorado's electricity system, built with [PyPSA](https://pypsa.org).

This repository is the code-and-data deposit accompanying:

> Dahlke, S. "Electricity capacity expansion aligned to state jurisdiction:
> Application to Colorado." Preprint: [SSRN link TBD].

If you use this model, please cite the paper above and this repository (see
[`CITATION.cff`](CITATION.cff)).

## What's here

- `pypsa/scripts/` — the model itself: network assembly, the myopic
  sequential solve loop, and the 8 demonstration cases reported in the paper.
- `data_cleaning/_scripts/` — the pipeline that builds the model's assembled,
  Colorado-specific input data from public federal and state sources (EIA,
  FERC, NREL, HIFLD, Colorado state agencies).
- `data_cleaning/` (data files) — the assembled inputs those scripts produce:
  zone topology and transfer limits, load forecasts and hourly shapes,
  renewable capacity-factor profiles, the existing generator fleet, candidate
  technology costs, fuel prices, and CO2 policy targets.
- `pypsa/scenarios/{case}/` — solved results for each of the paper's 8 cases
  (capacity, generation, cost, CO2, and resource-adequacy tables by year).

## Quickstart

Developed and tested on Python 3.12.7. Compatibility with other Python
versions hasn't been checked yet.

```bash
pip install -r requirements.txt
python -u pypsa/scripts/run_scenarios.py core
```

This re-solves the paper's Reference case from the assembled inputs already
in this repository — no external data downloads or API keys needed. Each
five-year investment sequence (2030-2050) takes roughly 20-50 minutes,
depending on the case and your machine. Output lands in
`pypsa/scenarios/core/`.

To run a different case, pass its name instead of `core` (see the table
below). Passing no argument at all also runs `core`.

## The 8 cases

| Case | What it represents | Where it appears in the paper |
|---|---|---|
| `core` | Reference case: Colorado's statutory CO2 policy, current transmission, full trade with neighbors | Main text — Figure 2, Table 4 |
| `island` | Colorado isolated from electricity trade with neighboring systems | Main text — Figure 3, Table 4 |
| `no_co2_policy` | Reference case with the CO2 constraint removed | Main text — Figure 3, Table 4 |
| `island_no_co2_policy` | Island + no CO2 policy, combined | Discussion |
| `cap95` | An alternative CO2 policy trajectory (95% cap, no ramp to 100%) | Discussion |
| `island_cap95` | Island + the `cap95` policy, combined | Discussion |
| `unconstrained_internal` | Internal transfer limits relaxed to an effectively unconstrained ("copper plate") level | Discussion — the transmission/wind-siting sensitivity |
| `island_unconstrained_internal` | Island + unconstrained internal transmission, combined | Discussion |

Every case is a named overlay on `core`'s defaults — see the `CASES` dict at
the top of `pypsa/scripts/run_scenarios.py`.

## Adapting this model to another state or system

The zone topology, transfer limits, load, renewable resources, generator
fleet, candidate technology costs, fuel prices, and CO2 policy targets are
all driven by CSVs under `data_cleaning/` — swapping in a different state's
data for these should not require touching `pypsa/scripts/model_helpers.py`.
Adding a new CO2 policy trajectory follows the same pattern: drop a
`year, co2_reduction_pct_vs_2005` CSV under `data_cleaning/policy/co2_paths/`
and pass its name as the `co2_path` argument (see `cap95` for an example) —
don't add a new boolean flag for a new policy scenario.

A handful of structural assumptions are Python constants in
`model_helpers.py` rather than CSV-driven, and would need to be found and
edited directly for a materially different system:

- `INVESTMENT_YEARS` — the five-year, 2030-2050 modeling horizon. Nothing
  downstream has been tested against a different horizon or step size.
- The single statewide planning-reserve-margin assumption (rather than a
  per-balancing-authority one) — a deliberate simplification for Colorado's
  two-BA structure, not a general solution.
- `HYBRID_BATTERY_MW_PER_SOLAR_MW` — the fixed solar-plus-storage sizing
  ratio, sourced from NREL ATB's default hybrid configuration.
- `UNCONSTRAINED_LINK_MW` — the "effectively unconstrained" transmission
  stand-in used by the `*_unconstrained_internal` cases, sized against
  Colorado's own statewide peak demand (~10 GW).
- The neighboring-system representation (`_add_external_market_generators`)
  — external markets are modeled as energy-only, priced and rated at the
  candidate combined-cycle gas unit's cost and emissions rate. This is a
  documented simplification; see
  the paper's Discussion for the reasoning and alternatives considered.

## Data sources and licensing

All underlying data comes from public sources (EIA, FERC, NREL, HIFLD, PUDL,
Colorado state agencies) — see the paper's Table 2 and Supplementary
Information for the full source list. Code in this repository is released
under the MIT license (see [`LICENSE`](LICENSE)).

Some large, national-scale raw source downloads (e.g., NREL's Electrification
Futures Study load profiles, national wind-resource rasters, Census county
shapefiles) are used by the `data_cleaning/_scripts/` pipeline but are not
included in this deposit — they are already public and citable at their
original source (see the paper's Table 2 and Supplementary Information for
the full source list), and re-hosting multi-gigabyte copies here would add
size without adding reproducibility. This repository includes the *outputs*
of that pipeline (the assembled, Colorado-specific CSVs under
`data_cleaning/`), which is what `run_scenarios.py` actually reads.

## Reproducibility scope

This repository lets you **reproduce the paper's reported cases** from the
assembled inputs already included here, using a pinned environment, that's
what `run_scenarios.py` is for.

The numbered scripts under `data_cleaning/_scripts/` are also included, and
show how those assembled inputs were built from raw public sources, but
**rebuilding them from scratch is not a one-command process** — it requires
API keys (NREL NSRDB/WIND Toolkit), access to public data lakes (PUDL's S3
bucket), and manually downloading a few federal workbooks (EIA's Annual
Energy Outlook tables). They're included for transparency, not as a promised
reproducible pipeline.
