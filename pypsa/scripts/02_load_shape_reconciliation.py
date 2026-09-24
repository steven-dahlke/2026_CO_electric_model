"""
PyPSA Milestone 2: load shape reconciliation to seasonal peaks + annual energy.

Milestone 1's build_load_timeseries() produces a load shape from NREL ResStock/ComStock (AMY2018,
actual 2018 weather) -- a legitimate, weather-driven source, but one whose implied seasonal peak
timing turned out inconsistent with FERC 714 (authoritative utility-filed peak forecasts, already
computed in data_cleaning/load/zone_allocated_peaks_2025.csv). Confirmed with real numbers: every
zone's shape-implied peaks diverge from FERC 714, from mild (East) to severe (South, Mountain).
Neither PyPSA nor (unlike EnCompass, which appears to reconcile this internally via its own
MthPeak mechanism -- not independently verifiable, proprietary) has any built-in way to fix this,
so it has to be an explicit PyPSA-side step. See pypsa/Documentation/build_plan.md, Milestone 2,
for the full design discussion (method selection, why the two simpler approaches tried first were
rejected, why this is re-solved fresh per target_year rather than cached).

This does NOT replace build_load_timeseries() -- Milestone 1's raw shape is still built the same
way. This module consumes that output and produces a reconciled version; everything downstream of
here (Milestone 3's representative-period selection onward) should call
reconcile_load_shape(target_year) instead of build_load_timeseries(target_year) directly.

Method (v2 -- replaced the original per-hour box-constrained QP, see below for why): the reconciled
load is expressed as a smooth, time-varying multiplicative adjustment to the original shape,
x(t) = s(t) * (1 + m(t)), where m(t) is a low-order Fourier series in time-of-year (N_HARMONICS
harmonics plus a constant term -- 2*N_HARMONICS+1 unknowns total, vs. 8760 in the original
formulation). Restricting m(t) to a handful of low-frequency harmonics means it can only vary
gradually across weeks/months by construction -- it has no vocabulary to represent a single-hour
discontinuity, so smoothness is structural rather than penalized. The Fourier coefficients are
chosen to minimize sum_h m(t_h)^2 subject to three linear constraints (m hits each season's
peak-anchor ratio at that season's original-shape peak hour, plus the annual energy balance) --
since the objective is quadratic and all three constraints are linear in the coefficients, the
optimum is a single small KKT linear system (numpy.linalg.solve, ~13 unknowns, no iteration).

Why v2: the original per-hour formulation (pin the season's peak hour to its target via a hard
equality, cap every other hour at the same target, solve via Lagrangian bisection) reproduced peak
and energy targets exactly, but real diagnostic output showed it also produced an implausible
single-hour spike at the pinned peak whenever the required correction was large relative to that
hour's original neighborhood -- confirmed in 5 of 6 zones (e.g. Mountain's summer peak jumped from
~229 MW to 392 MW in one hour and back to ~233 MW the next). Adding a smoothness penalty to that
formulation was tried and found computationally impractical: both scipy's trust-constr (given
correct analytic gradient and Hessian) and HiGHS's QP solver failed to converge on a single zone
within several minutes at full 8760-hour resolution -- HiGHS's QP algorithm is an active-set
method, and its iteration count blows up non-linearly as the number of simultaneously-active box
constraints grows, which is exactly what a smoothness-coupled version of this problem has. The
Fourier approach sidesteps this entirely by shrinking the problem to ~13 unknowns instead of 8760,
rather than trying to keep 8760 unknowns tractable under added coupling.

Safeguard: anchoring the curve to hit each season's target at exactly one hour does not, by itself,
guarantee a neighboring hour can't edge slightly above the same target (unlike the old per-hour box
constraints, which guaranteed this exactly). Confirmed empirically (North zone, 2035: winter peak
overshot its target by ~6 MW / 0.4% at a single hour). Handled by clipping any post-solve
exceedance to the target and redistributing the resulting energy shortfall proportionally across
the rest of that season's hours -- see _redistribute_overshoot().

Season split -- full 12-month binary partition, no "shoulder" category. Checked empirically before
deciding: every shoulder month's peak (Apr/May/Oct/Nov), in every zone, sits much closer to the
winter target than the summer one (summer's target is dominated by an AC-driven spike shoulder
months don't have). So: Summer = Jun-Sep (matches the NERC/Script 6 convention already used
elsewhere), Winter = everything else (Oct-May, 8 months) -- every hour gets exactly one of the two
caps, closing a real "spillage" gap an earlier shoulder-as-unconstrained design had (nothing would
have stopped an October or April hour from exceeding both seasonal targets).
"""

import os
import sys
import importlib

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import find_project_root

timeseries_assembly = importlib.import_module("01_timeseries_assembly")
build_load_timeseries = timeseries_assembly.build_load_timeseries

PROJECT_ROOT = find_project_root()
LOAD_DIR = PROJECT_ROOT / "data_cleaning" / "load"
OUT_DIR = PROJECT_ROOT / "pypsa" / "diagnostics"

FERC_PEAKS_PATH = LOAD_DIR / "zone_allocated_peaks_2025.csv"
GROWTH_PATH = LOAD_DIR / "I_zt_load_forecast_indices_CO_through_2050.csv"

BASE_YEAR = 2025
ZONES = ["Denver", "East", "Mountain", "North", "South", "West"]
SUMMER_MONTHS = [6, 7, 8, 9]  # NERC convention, matches data_cleaning Script 6

# Number of Fourier harmonics for the smooth reshaping envelope m(t) -- empirically chosen against
# 2035 data across all 6 zones (see module docstring). Verified there to eliminate the single-hour
# spike from the original per-hour formulation while still hitting peak/energy targets almost
# exactly. Re-verify against other years if this stops looking right -- not derived analytically.
N_HARMONICS = 6


def _scaled_peak_targets(target_year: int) -> pd.DataFrame:
    """FERC-714-allocated summer/winter peaks (2025 base year) scaled to target_year via the same
    ratio-of-growth-index pattern build_load_timeseries() already uses for energy -- summer and
    winter use their own index columns (summer_peak_demand_forecast_mw_idx /
    winter_peak_demand_forecast_mw_idx), not the energy index, since these are confirmed to grow
    at different rates (see module docstring / build_plan.md)."""
    base_peaks = pd.read_csv(FERC_PEAKS_PATH).set_index("zone")
    growth = pd.read_csv(GROWTH_PATH)

    rows = []
    for zone in ZONES:
        idx_summer_target = float(growth.loc[
            (growth["zone"] == zone) & (growth["forecast_year"] == target_year),
            "summer_peak_demand_forecast_mw_idx"
        ].iloc[0])
        idx_summer_base = float(growth.loc[
            (growth["zone"] == zone) & (growth["forecast_year"] == BASE_YEAR),
            "summer_peak_demand_forecast_mw_idx"
        ].iloc[0])
        idx_winter_target = float(growth.loc[
            (growth["zone"] == zone) & (growth["forecast_year"] == target_year),
            "winter_peak_demand_forecast_mw_idx"
        ].iloc[0])
        idx_winter_base = float(growth.loc[
            (growth["zone"] == zone) & (growth["forecast_year"] == BASE_YEAR),
            "winter_peak_demand_forecast_mw_idx"
        ].iloc[0])

        rows.append({
            "zone": zone,
            "summer_target": base_peaks.loc[zone, "allocated_summer_peak_MW"] * (idx_summer_target / idx_summer_base),
            "winter_target": base_peaks.loc[zone, "allocated_winter_peak_MW"] * (idx_winter_target / idx_winter_base),
        })
    return pd.DataFrame(rows).set_index("zone")


def _fourier_basis(n: int, K: int) -> np.ndarray:
    """n x (2K+1) design matrix for m(t) = c0 + sum_k[a_k*cos(2*pi*k*t/n) + b_k*sin(2*pi*k*t/n)]."""
    t = np.arange(n)
    cols = [np.ones(n)]
    for k in range(1, K + 1):
        cols.append(np.cos(2 * np.pi * k * t / n))
        cols.append(np.sin(2 * np.pi * k * t / n))
    return np.column_stack(cols)


def _redistribute_overshoot(x: np.ndarray, mask: np.ndarray, target: float,
                             max_passes: int = 5) -> np.ndarray:
    """Clips any hour in `mask` exceeding `target`, redistributing the shortfall proportionally
    across the remaining (non-violating) hours in `mask` -- see module docstring's Safeguard note.
    Re-checks after each redistribution rather than assuming one pass is enough."""
    x = x.copy()
    for _ in range(max_passes):
        violating = mask & (x > target + 1e-9)
        if not violating.any():
            break
        excess = (x[violating] - target).sum()
        x[violating] = target
        remaining = mask & ~violating
        if not remaining.any():
            break
        x[remaining] += excess * (x[remaining] / x[remaining].sum())
    return x


def _reconcile_one_zone(s: np.ndarray, months: np.ndarray, p_summer: float, p_winter: float,
                         e_target: float) -> tuple[np.ndarray, np.ndarray]:
    """Fourier-based smooth reshaping solve for one zone. See module docstring for the math and
    for why this replaced the original per-hour box-constrained QP.

    Returns (x, m): x is the final reconciled shape (post-safeguard), m is the raw fitted
    calibration envelope from the Fourier solve, before the safeguard's clip/redistribute step --
    this is m(h) as defined in the writeup, useful as a diagnostic in its own right (see
    reconcile_load_shape's return_envelope option)."""
    n = len(s)
    summer_mask = np.isin(months, SUMMER_MONTHS)
    winter_mask = ~summer_mask

    h_summer_star = np.argmax(np.where(summer_mask, s, -np.inf))
    h_winter_star = np.argmax(np.where(winter_mask, s, -np.inf))

    Phi = _fourier_basis(n, N_HARMONICS)
    m_dim = Phi.shape[1]

    # minimize c^T (Phi^T Phi) c  s.t.  A c = b  (3 linear constraints: 2 peak anchors + energy)
    H = 2 * (Phi.T @ Phi)
    A = np.vstack([
        Phi[h_summer_star],
        Phi[h_winter_star],
        (s[:, None] * Phi).sum(axis=0),
    ])
    b = np.array([
        p_summer / s[h_summer_star] - 1.0,
        p_winter / s[h_winter_star] - 1.0,
        e_target - s.sum(),
    ])

    # small KKT system: [[H, A^T],[A, 0]] [c; nu] = [0; b]
    KKT = np.block([[H, A.T], [A, np.zeros((3, 3))]])
    rhs = np.concatenate([np.zeros(m_dim), b])
    c = np.linalg.solve(KKT, rhs)[:m_dim]

    m = Phi @ c
    x = s * (1 + m)

    x = _redistribute_overshoot(x, summer_mask, p_summer)
    x = _redistribute_overshoot(x, winter_mask, p_winter)

    return x, m


def reconcile_load_shape(
    target_year: int, return_envelope: bool = False
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    """Returns the reconciled 8760-hour load DataFrame (same shape/index as
    build_load_timeseries(target_year)'s output) -- every zone's summer and winter peak hits its
    FERC-714-derived target exactly, and total annual energy is unchanged from
    build_load_timeseries()'s own total (which already correctly reflects the annual energy
    forecast for target_year by construction, per Milestone 1's own growth-index scaling -- not an
    assumption, this function doesn't need a separate energy-forecast source).

    Always re-solved fresh for target_year, never cached across years -- summer peak, winter peak,
    and energy grow at different rates (confirmed in the actual growth-index data), so each year
    has a genuinely different peak-to-energy relationship.

    return_envelope=True additionally returns the raw fitted calibration envelope m(h) per zone
    (pre-safeguard) as a second DataFrame -- diagnostic-only, for inspecting the Fourier fit
    directly (see pypsa/diagnostics/load_shape_calibration_envelope_{year}.csv). Default is False
    so every existing caller (Milestone 3's select_representative_periods, etc.) is unaffected.
    """
    raw_load = build_load_timeseries(target_year)
    targets = _scaled_peak_targets(target_year)
    months = raw_load.index.month.values

    reconciled = pd.DataFrame(index=raw_load.index)
    envelope = pd.DataFrame(index=raw_load.index)
    for zone in ZONES:
        s = raw_load[zone].values
        e_target = s.sum()
        x, m = _reconcile_one_zone(
            s, months, targets.loc[zone, "summer_target"], targets.loc[zone, "winter_target"], e_target
        )
        reconciled[zone] = x
        envelope[zone] = m

    if return_envelope:
        return reconciled, envelope
    return reconciled


# Zone layout matches methods v1.docx Figure 3 ("Zonal load forecast indices") exactly, so a reader
# flipping between figures sees the same panel positions -- top row Denver/East/Mountain, bottom
# row North/South/West.
_FIGURE_ZONE_LAYOUT = [["Denver", "East", "Mountain"], ["North", "South", "West"]]


def plot_load_shape_comparison(years: tuple[int, int] = (2025, 2050), out_path=None):
    """Faceted chart, one zone per column-pair, comparing the reconciled hourly load shape between
    two planning years. Each zone gets two stacked panels (year_a above, year_b below) rather than
    overlaying both years on one axes -- overlaid, the later (larger) year's line visually buried
    the earlier one almost everywhere. The two panels within a zone share a y-axis scale, so growth
    between the years is still directly readable; scale is independent across zones.

    Styled to match methods v1.docx's existing figures (see Figure 3, "Zonal load forecast
    indices"): serif typeface, shared borderless legend above the grid, minimal spines, no
    gridlines, panel titles are bare zone names with no in-image caption (captions are added in
    Word, same as the other figures). Zone column order matches Figure 3 exactly (Denver/East/
    Mountain, North/South/West) so a reader flipping between figures recognizes the layout.

    Two deliberate departures from Figure 3's exact style, not oversights:
      - No point markers on the lines -- Figure 3 has ~10 points per line (annual, one per
        forecast year); this has 8,760 (hourly), so markers would be unreadable clutter.
      - Independent y-axis scale per zone, not shared figure-wide -- Figure 3's shared y-axis works
        because it plots a normalized index (every zone starts at 1.0); this plots raw MW, which
        spans roughly a 20x range across zones (Denver's peak is ~20x Mountain's), so sharing one
        scale figure-wide would flatten the smaller zones into visually meaningless near-flat
        lines. Sharing it within each zone's own pair of panels, though, is exactly what makes the
        year-over-year growth comparable.

    Saved as a PNG diagnostic, not auto-embedded anywhere -- pull it into the writeup manually like
    the other figures.
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    plt.rcParams["font.family"] = "serif"
    plt.rcParams["font.size"] = 13

    year_a, year_b = years
    load_a = reconcile_load_shape(year_a)
    load_b = reconcile_load_shape(year_b)
    colors = {year_a: "#2166AC", year_b: "#B2182B"}

    fig, axes = plt.subplots(4, 3, figsize=(11, 9.5))
    for zone_row in range(2):
        for zone_col in range(3):
            zone = _FIGURE_ZONE_LAYOUT[zone_row][zone_col]
            ax_a = axes[2 * zone_row, zone_col]
            ax_b = axes[2 * zone_row + 1, zone_col]

            ax_a.plot(load_a.index, load_a[zone].values, color=colors[year_a],
                      linewidth=0.4, label=str(year_a))
            ax_b.plot(load_b.index, load_b[zone].values, color=colors[year_b],
                      linewidth=0.4, label=str(year_b))
            ax_a.set_title(zone, fontsize=17)

            ymin = min(load_a[zone].min(), load_b[zone].min())
            ymax = max(load_a[zone].max(), load_b[zone].max())
            pad = (ymax - ymin) * 0.05
            for ax in (ax_a, ax_b):
                ax.set_ylim(ymin - pad, ymax + pad)
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                ax.margins(x=0)
                ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
            ax_a.tick_params(labelbottom=False)  # month labels once per zone pair, on the bottom panel

    handles = [axes[0, 0].lines[0], axes[1, 0].lines[0]]
    labels = [str(year_a), str(year_b)]
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False,
               bbox_to_anchor=(0.5, 1.02), fontsize=15)
    fig.supylabel("Load (MW)", fontsize=16)
    fig.supxlabel("Month", fontsize=16)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    if out_path is None:
        out_path = OUT_DIR / f"load_shape_comparison_{year_a}_vs_{year_b}.png"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> None:
    print("\n--- PyPSA Milestone 2: load shape reconciliation ---")

    target_year = 2035
    print(f"\nReconciling load shape for target_year={target_year}...")

    raw_load = build_load_timeseries(target_year)
    reconciled, envelope = reconcile_load_shape(target_year, return_envelope=True)
    targets = _scaled_peak_targets(target_year)
    months = raw_load.index.month.values
    summer_mask = np.isin(months, SUMMER_MONTHS)
    winter_mask = ~summer_mask
    shoulder_mask = np.isin(months, [4, 5, 10, 11])

    print("\n--- Validation ---")
    print(f"{'zone':<10}{'summer_new':>12}{'summer_tgt':>12}{'winter_new':>12}{'winter_tgt':>12}"
          f"{'E_new':>14}{'E_orig':>14}")
    for zone in ZONES:
        s_new = reconciled[zone].values
        s_orig = raw_load[zone].values
        print(f"{zone:<10}{s_new[summer_mask].max():>12,.1f}{targets.loc[zone,'summer_target']:>12,.1f}"
              f"{s_new[winter_mask].max():>12,.1f}{targets.loc[zone,'winter_target']:>12,.1f}"
              f"{s_new.sum():>14,.0f}{s_orig.sum():>14,.0f}")

    print("\nSpecific check: South's shoulder months (the case that broke the earlier 3-group method):")
    s_new = reconciled["South"].values
    s_orig = raw_load["South"].values
    ratio = s_new[shoulder_mask].mean() / s_orig[shoulder_mask].mean()
    print(f"  Original shoulder mean: {s_orig[shoulder_mask].mean():.2f}, "
          f"New: {s_new[shoulder_mask].mean():.2f}, ratio: {ratio:.3f} "
          f"(1.0 = unchanged; 3-group method previously gave 0.406)")
    if abs(ratio - 1.0) > 0.1:
        print("  *** CHECK: shoulder months distorted more than expected ***")

    print("\nMax relative deviation from original shape, all zones:")
    for zone in ZONES:
        s_new = reconciled[zone].values
        s_orig = raw_load[zone].values
        rel = np.abs((s_new - s_orig) / s_orig)
        print(f"  {zone:<10} mean={rel.mean():.4f}  max={rel.max():.4f}")

    print("\nSmoothness check (max hour-to-hour jump, reconciled vs. raw -- catches the single-hour "
          "spike the original per-hour formulation produced):")
    for zone in ZONES:
        s_new = reconciled[zone].values
        s_orig = raw_load[zone].values
        new_jump = np.max(np.abs(np.diff(s_new)))
        orig_jump = np.max(np.abs(np.diff(s_orig)))
        flag = "" if new_jump <= orig_jump * 1.5 else "  *** CHECK: jump much larger than raw shape's own noise ***"
        print(f"  {zone:<10} reconciled_max_jump={new_jump:>8.2f}  raw_max_jump={orig_jump:>8.2f}{flag}")

    print("\nPost-safeguard exceedance check (should be zero hours for every zone):")
    for zone in ZONES:
        s_new = reconciled[zone].values
        n_over_summer = int((s_new[summer_mask] > targets.loc[zone, "summer_target"] + 0.5).sum())
        n_over_winter = int((s_new[winter_mask] > targets.loc[zone, "winter_target"] + 0.5).sum())
        flag = "" if (n_over_summer == 0 and n_over_winter == 0) else "  *** CHECK: safeguard did not fully clear exceedance ***"
        print(f"  {zone:<10} hours_over_summer_target={n_over_summer}  hours_over_winter_target={n_over_winter}{flag}")

    print("\nNegative-value check (should be none):")
    for zone in ZONES:
        n_neg = int((reconciled[zone].values < 0).sum())
        print(f"  {zone:<10} negative_hours={n_neg}  min_value={reconciled[zone].values.min():.2f}")

    print(f"\nSaving diagnostics to {OUT_DIR.relative_to(PROJECT_ROOT)}...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reconciled.to_csv(OUT_DIR / f"load_shape_reconciled_{target_year}.csv")
    print(f"  load_shape_reconciled_{target_year}.csv")
    envelope.to_csv(OUT_DIR / f"load_shape_calibration_envelope_{target_year}.csv")
    print(f"  load_shape_calibration_envelope_{target_year}.csv  (raw fitted m(h) per zone, "
          f"pre-safeguard)")


if __name__ == "__main__":
    main()
