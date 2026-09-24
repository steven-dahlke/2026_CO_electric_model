"""
PyPSA Milestone 3: representative period selection.

Reduces the full 8760-hour snapshot calendar to a smaller set of representative weeks the
capacity-expansion LP can actually solve -- Milestone 5's first full-8760 solve attempt produced a
3.19M-row/1.48M-column LP that neither HiGHS's default dual simplex nor its interior-point method
converged on in reasonable time. See pypsa/Documentation/build_plan.md, Milestone 3, for the full
design discussion and reasoning (why weekly periods, why tsam, why k-medoids, what stays in our
own code vs. delegated to the library, the year-invariance robustness discussion).

Uses tsam (https://github.com/FZJ-IEK3-VSA/tsam), the same tool PyPSA-Eur uses for this purpose --
called narrowly (k-medoids clustering + extreme-period forcing only), with the surrounding data
prep, PyPSA-facing weighting translation, and validation kept in our own code.

API note: tsam 4.0.0 (the version that actually installed) uses a different, newer functional API
(tsam.aggregate(), ClusterConfig/ExtremeConfig) than the class-based TimeSeriesAggregation API
documented at readthedocs.io/en/v3.1.1 -- verified directly against the installed package (see
inline comments below) rather than trusting either doc source blindly, per the plan's explicit
first implementation step.

Clusters on the *reconciled* load shape (Milestone 2's reconcile_load_shape(), not Milestone 1's
raw build_load_timeseries() directly) -- Milestone 2 corrects the raw shape's seasonal peak timing
to match FERC 714 before anything downstream uses it; clustering the raw shape would mean
representative weeks selected against a load pattern known to be wrong.
"""

import os
import sys
import importlib

import pandas as pd
import tsam

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import find_project_root
from model_helpers import resolve_cf_column

# None of 01_timeseries_assembly.py / 02_load_shape_reconciliation.py / 04_resource_assembly.py is
# a valid Python identifier (all start with a digit) -- importlib doesn't have that restriction,
# same pattern already used in 05_single_year_pilot.py.
timeseries_assembly = importlib.import_module("01_timeseries_assembly")
load_shape_reconciliation = importlib.import_module("02_load_shape_reconciliation")
resource_assembly = importlib.import_module("04_resource_assembly")
build_cf_timeseries = timeseries_assembly.build_cf_timeseries
reconcile_load_shape = load_shape_reconciliation.reconcile_load_shape
build_existing_fleet_components = resource_assembly.build_existing_fleet_components

PROJECT_ROOT = find_project_root()
OUT_DIR = PROJECT_ROOT / "pypsa" / "diagnostics"

# Weekly periods, not daily -- chosen specifically because the longest storage duration in the
# fleet post-aggregation (North_Hydro:Pumped_agg, 23.88hr) needs real room to cycle within one
# period; 168hr gives ~7x headroom, 24hr would leave almost none. See build_plan.md Milestone 3.
HOURS_PER_PERIOD = 168

# Starting point, explicitly tunable -- not derived from data yet. Revisit based on the
# energy-conservation validation below and, later, the resulting LP size/solve time once wired
# into Milestone 5.
N_TYPICAL_PERIODS = 10

# Spot-check years spanning the planning horizon -- matches the multi-year verification pattern
# already used for Milestones 1/2/4's own logic. Not necessarily the exact set of years the
# eventual multi-year model will solve for; just a representative spread for diagnostics.
PLANNING_YEARS = [2025, 2030, 2035, 2040, 2045, 2050]


def _compute_system_net_load(load: pd.DataFrame, cf: pd.DataFrame, target_year: int) -> pd.Series:
    """Total system load minus existing *committed* solar/wind generation, used only to identify
    which real week contains the year's true peak net-load hour (fed to tsam's ExtremeConfig).

    Deliberately uses only existing-fleet capacity, not any hypothetical candidate build-out --
    the representative-period selection has to be usable *before* the model has decided what to
    build, so it can't depend circularly on that decision.
    """
    existing_gen, _ = build_existing_fleet_components(target_year)
    renewables = existing_gen[existing_gen["carrier"].isin(["Solar:PV", "Wind"])]

    renewable_mw = pd.Series(0.0, index=cf.index)
    for name, row in renewables.iterrows():
        col = resolve_cf_column(name, row["carrier"], row["bus"])
        if col is not None:
            renewable_mw = renewable_mw + cf[col].values * row["p_nom"]

    return load.sum(axis=1) - renewable_mw


def select_representative_periods(
    target_year: int, n_typical_periods: int = N_TYPICAL_PERIODS, return_periods: bool = False
):
    """Returns (representative_snapshots, snapshot_weightings) -- a subset of the full 8760-hour
    2018-dated calendar (real calendar weeks, not synthetic composites) plus an objective-style
    weight per snapshot (how many real weeks that pattern stands in for).

    `target_year` is always required, matching every other Milestone 1/2/4 function -- a deliberate
    robustness choice, not an oversight. Under today's uniform-per-zone load growth model this
    produces an identical result regardless of which year is passed (safe for a caller to memoize
    across periods as an optimization), but if sector-differentiated growth rates are ever
    implemented (changing load's relative *shape*, not just magnitude, over time), this function
    needs zero code changes -- it was always correctly parameterized. See build_plan.md.

    return_periods=True additionally returns the list of (period_snapshots, weight) pairs, one per
    selected period, *before* they get flattened into representative_snapshots/snapshot_weightings.
    Needed because periods are not guaranteed to all be HOURS_PER_PERIOD long: 8760 hours isn't a
    whole multiple of 168, so tsam pads the year's last period to make the clustering reshape work,
    then correctly shrinks that period's weight to match its real (shorter) length if it gets
    selected as a representative -- this is tsam's documented, intentional behavior (see
    tsam/pipeline/periods.py's unstack_to_periods docstring), not a bug. Downstream code that
    reports or iterates per-period (summaries, CSVs) must use these real boundaries rather than
    re-deriving them by assuming a fixed 168-hour stride over the flattened arrays, which silently
    misaligns every period after a short one. Default False, so the one existing caller (this
    module's own main()) is the only thing that opts in; a future Milestone 5 caller can too once
    it needs per-period boundaries for the storage-continuity design.
    """
    load = reconcile_load_shape(target_year)
    cf = build_cf_timeseries()
    system_net_load = _compute_system_net_load(load, cf, target_year)

    input_df = pd.concat([load, cf], axis=1)
    input_df["system_net_load"] = system_net_load

    # scale_by_column_means: tsam's native min-max-then-divide-by-mean normalization -- handles
    # the mixed-unit problem (MW-scale load vs. 0-1 capacity factors) natively, so no separate
    # hand-rolled normalization step is needed (verified this option exists directly against the
    # installed API before relying on it, not assumed).
    # include_period_sums (added after first run showed a systematic +2.7%-4.5% energy
    # over-estimate across every zone): makes clustering weight total-period-energy similarity,
    # not just shape similarity -- a medoid inherently won't exactly match its cluster's true
    # average (that's the k-means/k-medoids trade-off we already made deliberately, for real
    # traceable weeks over synthetic composites), but this should narrow the gap by making the
    # clustering itself favor medoids whose totals are more representative.
    result = tsam.aggregate(
        input_df,
        n_clusters=n_typical_periods,
        period_duration=HOURS_PER_PERIOD,
        cluster=tsam.ClusterConfig(
            method="kmedoids", scale_by_column_means=True, include_period_sums=True, solver="highs"
        ),
        extremes=tsam.ExtremeConfig(method="new_cluster", max_value=["system_net_load"]),
    )

    clustering = result.clustering
    if clustering.cluster_centers is None:
        raise RuntimeError(
            "tsam did not return cluster_centers -- expected for method='kmedoids' "
            "(representation defaults to 'medoid'), needed to map clusters back to real weeks."
        )

    time_index = clustering.time_index
    snapshots_list = []
    weight_list = []
    periods = []  # (period_snapshots, weight) per selected period, real lengths preserved
    for cluster_idx, period_idx in enumerate(clustering.cluster_centers):
        start = period_idx * HOURS_PER_PERIOD
        end = start + HOURS_PER_PERIOD
        week_snapshots = time_index[start:end]  # shorter than HOURS_PER_PERIOD for the padded
        # year-end period, if selected -- see this function's return_periods docstring note.
        weight = result.cluster_counts[cluster_idx]
        snapshots_list.append(week_snapshots)
        weight_list.extend([weight] * len(week_snapshots))
        periods.append((week_snapshots, weight))

    representative_snapshots = pd.DatetimeIndex(snapshots_list[0].append(snapshots_list[1:]))
    snapshot_weightings = pd.Series(weight_list, index=representative_snapshots, name="objective")

    if return_periods:
        return representative_snapshots, snapshot_weightings, periods
    return representative_snapshots, snapshot_weightings


def main() -> None:
    print("\n--- PyPSA Milestone 3: representative period selection ---")

    target_year = 2035
    print(f"\nSelecting representative periods for target_year={target_year}...")
    print(f"hours_per_period={HOURS_PER_PERIOD}, n_typical_periods={N_TYPICAL_PERIODS}")

    representative_snapshots, snapshot_weightings, periods = select_representative_periods(
        target_year, N_TYPICAL_PERIODS, return_periods=True
    )

    print(f"\nSelected {len(representative_snapshots)} snapshots ({len(periods)} periods)")

    print("\n--- Validation ---")

    total_weighted_hours = snapshot_weightings.sum()
    print(f"Total weighted hours: {total_weighted_hours:.1f} (expect ~8760)")

    print("\nRepresentative periods (real calendar dates, weight = # of real periods represented):")
    for week, weight in periods:
        short_flag = (
            f"  *** SHORT PERIOD: {len(week)}h, not a full {HOURS_PER_PERIOD}h week -- "
            "tsam's year-end padding case, see select_representative_periods docstring ***"
            if len(week) != HOURS_PER_PERIOD else ""
        )
        print(f"  {week[0].strftime('%Y-%m-%d %H:%M')} to {week[-1].strftime('%Y-%m-%d %H:%M')}  "
              f"({len(week)}h)  weight={weight:.2f}{short_flag}")

    # Independent annual energy conservation check -- our own code, not trusting tsam's accuracy
    # metrics alone.
    load_full = reconcile_load_shape(target_year)
    cf_full = build_cf_timeseries()
    print("\nEnergy conservation check (weighted representative sum vs. true annual total):")
    for zone in load_full.columns:
        true_total = load_full[zone].sum()
        rep_values = load_full.loc[representative_snapshots, zone]
        # Weights are already calibrated to real-hour-equivalents (they sum to ~8760), so the
        # weighted sum of (value x weight) over representative hours is directly comparable to
        # the true full-year sum -- no additional scaling needed.
        weighted_total = (rep_values.values * snapshot_weightings.values).sum()
        pct_diff = (weighted_total - true_total) / true_total * 100
        flag = "" if abs(pct_diff) < 5 else "  *** CHECK ***"
        print(f"  {zone:<10} true={true_total:>12,.0f}  weighted={weighted_total:>12,.0f}  "
              f"diff={pct_diff:+.2f}%{flag}")

    # Confirm the true annual peak net-load hour is actually represented.
    system_net_load = _compute_system_net_load(load_full, cf_full, target_year)
    true_peak_hour = system_net_load.idxmax()
    peak_represented = true_peak_hour in representative_snapshots
    print(f"\nTrue annual peak net-load hour: {true_peak_hour} "
          f"({system_net_load.max():,.0f} MW)")
    print(f"Represented in selected snapshots: {peak_represented}")
    if not peak_represented:
        print("  *** CHECK: extreme-period forcing did not capture the true peak ***")

    print(f"\n--- Representative periods across the planning period {PLANNING_YEARS} ---")
    all_years_rows = []
    for year in PLANNING_YEARS:
        if year == target_year:
            # Already computed above -- avoid re-running tsam for the same year twice.
            year_periods, year_true_peak = periods, true_peak_hour
        else:
            _, _, year_periods = select_representative_periods(
                year, N_TYPICAL_PERIODS, return_periods=True
            )
            year_load = reconcile_load_shape(year)
            # cf_full is year-independent (Milestone 1's capacity factors don't vary by target_year),
            # so it's safe and cheaper to reuse rather than rebuild per year.
            year_net_load = _compute_system_net_load(year_load, cf_full, year)
            year_true_peak = year_net_load.idxmax()

        for week, weight in year_periods:
            all_years_rows.append({
                "year": year, "period_start": week[0], "period_end": week[-1],
                "n_hours": len(week), "weight": weight,
                "contains_true_peak": year_true_peak in week,
            })
        print(f"  {year}: {len(year_periods)} periods, true peak at {year_true_peak}")

    print(f"\nSaving diagnostics to {OUT_DIR.relative_to(PROJECT_ROOT)}...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_years_df = pd.DataFrame(all_years_rows)
    all_years_df.to_csv(OUT_DIR / "representative_weeks_summary.csv", index=False)
    print(f"  representative_weeks_summary.csv ({len(all_years_df)} rows)")


if __name__ == "__main__":
    main()
