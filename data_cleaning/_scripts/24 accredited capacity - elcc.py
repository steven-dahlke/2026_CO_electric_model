"""
Script 24: Accredited Capacity -- ELCC for Wind, Solar, and Storage

Builds elcc_lookup.csv -- a long-format (resource_set, technology, year) accredited-capacity
table for the resources Script 23 deliberately left blank (Solar:PV, Wind, Storage:Battery for
the existing fleet; Solar:PV, Wind, Solar+Storage, Storage:Battery for candidates), because a
flat forced-outage-rate derate would misstate their real capacity value at higher penetration.
Source: NREL's "Average and Marginal Capacity Credits of Renewable Energy and Battery Storage
in the United States Power System" (data.nlr.gov/submissions/250, built from 2023 Standard
Scenarios / ReEDS), Mid_Case scenario -- NREL's central/reference case, consistent with this
project's use of the central case everywhere else (ATB Moderate, AEO Reference/cb2026).

Does NOT write a single accredited_capacity_pct value onto colorado_resources.csv or
candidate_technology_parameters.csv -- ELCC is genuinely year-varying (unlike the flat
dispatchable EFORd derate), so it can't be squeezed into those files' single-scalar column the
way Script 23's dispatchable values were. Instead, this stays a standalone long-format
reference table -- same separation-of-concerns pattern already used for every other multi-year
trajectory in this project (atb_candidate_lookup.csv, fuel_price_lookup.csv,
ba_reserve_margin.csv): joined by (TechType/tech_class, year) at whatever future step actually
builds the EnCompass/PyPSA network, not pre-merged here. The two resource files' own
accredited_capacity_source values are updated to point here instead of the stale
"deferred_pending_elcc..." tag Script 23 left.

Average vs. marginal capacity credit maps directly onto this project's existing/candidate
split: avg_cc ("the average contribution existing resources can contribute to resource
adequacy") -> existing fleet; mar_cc ("the incremental contribution new resources can
contribute") -> candidates. This is a real methodological match, not a convenient relabeling --
marginal capacity credit for a new resource is lower than the average credit of the existing
fleet once penetration is high, which is exactly the "don't overstate capacity value at high
penetration" behavior this whole accreditation tier split was built around.

Geographic resolution: ReEDS BA regions (p33, p34 -- the only two covering Colorado, confirmed
via ReEDS's own public hierarchy.csv/county2zone.csv, github.com/NREL/ReEDS-2.0), not the
coarser 18-region Cambium GEA regions. Colorado's own 6-zone boundaries don't nest inside
p33/p34 (Denver/North/Mountain sit entirely in p33; South/East/West straddle both) -- rather
than a per-zone blend, which would only ever have applied to the existing fleet (candidates
have no zone dimension at all in candidate_technology_parameters.csv), this uses ONE statewide
value per technology (2026-08-05 decision, kept simple for this initial pass; revisit
granularity in a later scenario/model version if warranted). The statewide blend weight is
capacity-weighted, not a flat 50/50 split: computed once from existing Solar:PV/Wind/
Storage:Battery nameplate MW by zone (colorado_resources.csv), apportioned to p33/p34 by each
zone's county-count split (from the ReEDS county2zone crosswalk) since per-resource county data
isn't available in this project. Denver/North/Mountain are 100% p33; South/East/West are mixed.

Technology mapping:
  - avg_cc (existing, aggregated tech_agg column): Solar:PV -> solar_upv, Wind -> wind_ons,
    Storage:Battery -> battery_4 (matches the 4-hour duration used throughout this project,
    e.g. Script 18/21's storage_duration_hours).
  - mar_cc (candidates, resource-class-specific tech column): Solar:PV -> upv_5,
    Wind -> wind-ons_5 (both Class5, matching Script 20's already-established candidate
    resource-quality choice -- not a new assumption), Storage:Battery -> battery_4.
    Solar+Storage (hybrid) uses the battery's value directly (2026-08-05 decision) -- the
    battery is what actually provides firm capacity in a co-located pairing, since standalone
    solar has little/no capacity value at typical stress hours.
  - Real gap found and resolved: mar_cc's upv_5 only has rows in p34, not p33 -- irrelevant
    under the one-statewide-value decision (candidate solar simply uses p34's value, nothing to
    blend against).

Peak-stress-day selection: both files are resolved to many representative days per year
(szn column, e.g. y2012d009, y2012d223), not one value per season. Confirmed directly against
the downloaded files (not assumed): the highest_price column is a binary flag. For existing-
fleet technologies (avg_cc) and candidate solar/wind (mar_cc), the large majority of
(region, tech, year) groups have exactly one flagged row -- the same calendar day across every
technology within a region (day 182 / day 189 for p33), marking the system-wide summer
peak-stress period (WECC-Rocky Mountain is a confirmed summer-peaking assessment area, NERC
2025 LTRA). Candidate battery is a real exception -- ALL representative days come back flagged,
every year, both regions -- not a bug: unlike solar/wind's fixed-output-at-a-given-hour
question, battery's marginal capacity credit is apparently re-evaluated against price signals
most days, so NREL's own flag is already averaging across the full year for that series. This
technology-dependent behavior is respected as-is (never overridden with our own uniform
day-selection rule); see select_peak_day().

Three known data-quality issues found and handled explicitly (2026-08-05), not silently
papered over:
  - Existing Storage:Battery's single-flagged-day value snaps between a small number of
    discrete levels (e.g. 66.7%/100.0%) rather than drifting smoothly -- confirmed against the
    raw data this is NOT a real installed-capacity effect (capacity grows fairly steadily
    across the period) but a threshold artifact: a duration-limited resource either fully
    covers that year's evaluated stress window or it doesn't, and small year-to-year shifts in
    the window's length flip the ratio. Compared visually against a 3-solve-year rolling
    average before deciding this was noise, not signal (chart generated during this session,
    not saved to the repo) -- confirmed the raw series clusters into 3 discrete levels with no
    directional trend, unlike every other series (all of which were already smooth). Given
    there's no real trend to preserve, this series alone is flattened to a single statewide
    value: the median (not mean, to stay robust to the 100%-ceiling readings and land on an
    actually-observed value) across all 13 solve-years -- see flatten_to_median().
  - mar_cc's solar/wind (all resource classes, not just Class5 -- checked every one) are
    missing 2032-2044 entirely for Colorado's regions, most likely because ReEDS's Mid_Case run
    had no new Class5-tier solar/wind candidate build to evaluate marginal capacity credit
    against in that window. Linearly interpolated between the surrounding known years
    (2026-08-05 decision) rather than flat-held, since both series are moving fastest through
    exactly that window (solar falling, wind rising) and a flat-hold would misrepresent the
    trend more than a straight-line fill.
  - All remaining series (existing solar/wind, candidate solar/wind/battery) get a
    3-solve-year centered rolling average as a final smoothing pass, applied after
    interpolation -- addresses the same single-representative-day noise as the battery case,
    just less severely; confirmed via the same visual comparison that this barely changes
    these series (their raw trends were already smooth), so the smoothing carries little risk
    of erasing real signal while still guarding against an isolated-year outlier.

Open question, deliberately not resolved here (2026-08-05): once a candidate resource is
actually built by some future EnCompass/PyPSA optimization, should its accredited_capacity_pct
keep drawing from the marginal (mar_cc) curve for the rest of its operating life, or switch to
the average (avg_cc) curve once built? Marginal capacity credit is conceptually a build-year
signal (the value of adding one more unit *this year*, used to inform the investment decision)
-- once built, the resource becomes part of the installed stock, and its ongoing contribution
to system adequacy is arguably better represented by the fleet-average curve every subsequent
year, not frozen at its construction-year marginal value. This project currently treats
existing/candidate as a fixed data-source split (avg_cc vs. mar_cc respectively) with no
vintage-based transition -- reasonable for this data-gathering step, but a real resource-
assignment design decision that belongs at the actual model-build step, not here. Revisit then.

Output: data_cleaning/resources/elcc/elcc_lookup.csv -- one row per
(resource_set, technology, year), technology using this project's own names (Solar:PV, Wind,
Storage:Battery, Solar+Storage) not ReEDS's internal tech codes. accredited_capacity_pct is the
final value (interpolated where needed, then smoothed -- rolling average for most series, flat
statewide median for existing Storage:Battery); accredited_capacity_pct_raw is the
interpolated-but-unsmoothed value, kept alongside for transparency; interpolated flags which
rows were filled rather than sourced directly from NREL.
"""

import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT  = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"

RESOURCES_CSV    = DATA_CLEANING / "resources" / "colorado_resources.csv"
CANDIDATE_PARAMS_CSV = DATA_CLEANING / "resources" / "candidate_technology_parameters.csv"

RAW_DIR  = DATA_CLEANING / "resources" / "elcc" / "raw"
AVG_CSV  = RAW_DIR / "avg_cc_Mid_Case.csv"
MAR_CSV  = RAW_DIR / "mar_cc_Mid_Case.csv"
AVG_URL  = "https://data.nlr.gov/system/files/250/1728854599-avg_cc_Mid_Case.csv"
MAR_URL  = "https://data.nlr.gov/system/files/250/1728857459-mar_cc_Mid_Case.csv"

OUT_CSV = DATA_CLEANING / "resources" / "elcc" / "elcc_lookup.csv"

CO_REGIONS = ["p33", "p34"]
SCENARIO   = "Mid_Case"
FULL_YEARS = list(range(2026, 2051, 2))   # native ReEDS solve-year cadence
ROLLING_WINDOW = 3   # solve-years (centered) -- see module docstring

# Existing-fleet capacity by zone (colorado_resources.csv) -> apportioned to p33/p34 by each
# zone's county-count split (ReEDS county2zone.csv crosswalk) -- see module docstring.
ZONE_TECH_TYPES = ["Solar:PV", "Wind", "Storage:Battery"]
ZONE_P33_FRACTION: dict[str, float] = {
    "Denver": 9 / 9, "North": 3 / 3, "Mountain": 6 / 6,
    "South": 2 / 15, "East": 5 / 15, "West": 5 / 16,
}

# avg_cc (existing fleet): TechType -> tech_agg column value.
EXISTING_TECH_MAP = {
    "Solar:PV":        "solar_upv",
    "Wind":             "wind_ons",
    "Storage:Battery":  "battery_4",
}
# mar_cc (candidates): tech_class -> tech column value. Class5, matching Script 20.
CANDIDATE_TECH_MAP = {
    "Solar:PV":        "upv_5",
    "Wind":             "wind-ons_5",
    "Storage:Battery":  "battery_4",
}

# Colors reused from `20 candidate technology cost data.py`'s CANDIDATE_TECH_COLORS -- same
# technologies, kept visually consistent across the project's whole chart family.
TECH_COLORS: dict[str, str] = {
    "Solar:PV":        "#FDB863",
    "Wind":            "#74C476",
    "Storage:Battery": "#9970AB",
    "Solar+Storage":   "#C51B7D",
}

# Chart styling -- matches Script 20's plot_capex_trajectories()/plot_om_trajectories().
AVG_PLOT_OUT = DATA_CLEANING / "resources" / "elcc" / "existing_avg_elcc.png"
MAR_PLOT_OUT = DATA_CLEANING / "resources" / "elcc" / "candidate_marginal_elcc.png"
PLOT_FONT_SIZE      = 22
PLOT_TICK_LABELSIZE = 20


def download_if_missing(path: Path, url: str) -> Path:
    if path.exists():
        print(f"  Cached: {path.name}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {path.name} from NREL data catalog...")
    urllib.request.urlretrieve(url, path)
    print(f"  Saved: {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MB)")
    return path


def compute_statewide_weights() -> dict[str, float]:
    """Capacity-weighted p33/p34 split, from existing Solar:PV/Wind/Storage:Battery MW by zone."""
    resources = pd.read_csv(RESOURCES_CSV)
    sub = resources[resources["TechType"].isin(ZONE_TECH_TYPES)]
    zone_mw = sub.groupby("Area")["MaxCap"].sum()

    p33_mw = sum(zone_mw.get(z, 0) * f for z, f in ZONE_P33_FRACTION.items())
    p34_mw = sum(zone_mw.get(z, 0) * (1 - f) for z, f in ZONE_P33_FRACTION.items())
    total = p33_mw + p34_mw

    weights = {"p33": p33_mw / total, "p34": p34_mw / total}
    print(f"  Statewide ReEDS-region weights: p33={weights['p33']:.4f}  p34={weights['p34']:.4f}")
    return weights


def select_peak_day(df: pd.DataFrame, region_col: str, tech_col: str) -> pd.DataFrame:
    """Filter to the summer peak-stress representative day per (region, tech, year), identified
    by highest_price==1 (see module docstring). Averages the rare 2-day-tie groups."""
    peak = df[df["highest_price"] == 1]
    return (
        peak.groupby([region_col, tech_col, "t"], as_index=False)["Value"]
        .mean()
    )


def blend_statewide(peak_df: pd.DataFrame, region_col: str, tech_col: str,
                     tech_value: str, weights: dict[str, float]) -> pd.DataFrame:
    """Capacity-weighted blend of p33/p34 for a single technology, one row per year.
    Falls back to whichever single region has data if the other is missing entirely
    (e.g. candidate solar's upv_5, only present in p34)."""
    sub = peak_df[peak_df[tech_col] == tech_value]
    rows = []
    for year, year_sub in sub.groupby("t"):
        year_sub = year_sub.set_index(region_col)["Value"]
        present = [r for r in CO_REGIONS if r in year_sub.index]
        if not present:
            continue
        if len(present) == 1:
            value = year_sub[present[0]]
        else:
            w_sum = sum(weights[r] for r in present)
            value = sum(year_sub[r] * weights[r] for r in present) / w_sum
        rows.append({"year": int(year), "accredited_capacity_pct": round(100 * value, 2)})
    return pd.DataFrame(rows).sort_values("year")


def fill_and_smooth(blend: pd.DataFrame) -> pd.DataFrame:
    """Reindex to the full native solve-year grid, linearly interpolating any gap (e.g.
    candidate solar/wind's missing 2032-2044 -- a real gap in NREL's published data, see module
    docstring), then apply a 3-solve-year centered rolling average as the final smoothing pass.
    accredited_capacity_pct_raw keeps the interpolated-but-unsmoothed value for transparency."""
    full = pd.DataFrame({"year": FULL_YEARS})
    merged = full.merge(blend[["year", "accredited_capacity_pct"]], on="year", how="left")
    merged["interpolated"] = merged["accredited_capacity_pct"].isna()
    merged["accredited_capacity_pct"] = merged["accredited_capacity_pct"].interpolate(
        method="linear", limit_direction="both"
    )
    merged["accredited_capacity_pct_raw"] = merged["accredited_capacity_pct"].round(2)
    merged["accredited_capacity_pct"] = (
        merged["accredited_capacity_pct"]
        .rolling(window=ROLLING_WINDOW, center=True, min_periods=1)
        .mean()
        .round(2)
    )
    return merged[["year", "accredited_capacity_pct", "accredited_capacity_pct_raw", "interpolated"]]


def flatten_to_median(blend: pd.DataFrame) -> pd.DataFrame:
    """Existing Storage:Battery only (2026-08-05 decision) -- see module docstring for why:
    the raw per-year values are a threshold artifact with no real trend, so a single flat
    statewide value (median, not mean, to stay robust to 100%-ceiling readings and land on an
    actually-observed value) is used for every year instead of preserving the noise."""
    median_value = round(blend["accredited_capacity_pct"].median(), 2)
    full = pd.DataFrame({"year": FULL_YEARS})
    full["accredited_capacity_pct"] = median_value
    full["accredited_capacity_pct_raw"] = median_value
    full["interpolated"] = False
    return full


def build_lookup(weights: dict[str, float]) -> pd.DataFrame:
    avg = pd.read_csv(AVG_CSV, index_col=0)
    avg = avg[(avg["r"].isin(CO_REGIONS)) & (avg["scenario"] == SCENARIO)]
    avg_peak = select_peak_day(avg, "r", "tech_agg")

    mar = pd.read_csv(MAR_CSV, index_col=0)
    mar = mar[(mar["r"].isin(CO_REGIONS)) & (mar["scenario"] == SCENARIO) & mar["t"].notna()]
    mar_peak = select_peak_day(mar, "r", "tech")

    rows = []
    for tech_class, tech_value in EXISTING_TECH_MAP.items():
        blend = blend_statewide(avg_peak, "r", "tech_agg", tech_value, weights)
        if tech_class == "Storage:Battery":
            blend = flatten_to_median(blend)
            source = "nrel_avg_cc_mid_case_reeds_p33_p34_statewide_blend_flat_median"
        else:
            blend = fill_and_smooth(blend)
            source = "nrel_avg_cc_mid_case_reeds_p33_p34_statewide_blend_3yr_smoothed"
        blend["resource_set"] = "existing"
        blend["technology"]   = tech_class
        blend["source"]       = source
        rows.append(blend)

    for tech_class, tech_value in CANDIDATE_TECH_MAP.items():
        blend = blend_statewide(mar_peak, "r", "tech", tech_value, weights)
        blend = fill_and_smooth(blend)
        blend["resource_set"] = "candidate"
        blend["technology"]   = tech_class
        blend["source"]       = "nrel_mar_cc_mid_case_reeds_p33_p34_statewide_blend_3yr_smoothed"
        rows.append(blend)

    # Solar+Storage hybrid: battery's marginal capacity credit directly (2026-08-05 decision).
    battery_candidate = rows[-1].copy()  # last appended = candidate Storage:Battery
    battery_candidate["technology"] = "Solar+Storage"
    battery_candidate["source"] = "same_as_candidate_storage_battery_mar_cc"
    rows.append(battery_candidate)

    lookup = pd.concat(rows, ignore_index=True)
    return lookup[["resource_set", "technology", "year", "accredited_capacity_pct",
                    "accredited_capacity_pct_raw", "interpolated", "source"]]


def update_source_tags() -> None:
    """Point the two resource files' accredited_capacity_source at this lookup table instead of
    Script 23's stale 'deferred_pending_elcc...' tag. accredited_capacity_pct stays blank in
    both files -- even existing Storage:Battery, which resolved to a flat value, is still best
    read from elcc_lookup.csv rather than duplicated into a single-scalar column here."""
    new_source = "see_elcc_lookup_csv"

    resources = pd.read_csv(RESOURCES_CSV)
    mask = resources["TechType"].isin(["Solar:PV", "Wind", "Storage:Battery"])
    resources.loc[mask, "accredited_capacity_source"] = new_source
    resources.to_csv(RESOURCES_CSV, index=False)
    print(f"  Updated accredited_capacity_source for {mask.sum()} existing resources")

    params = pd.read_csv(CANDIDATE_PARAMS_CSV)
    mask = params["tech_class"].isin(["Solar:PV", "Wind", "Solar+Storage", "Storage:Battery"])
    params.loc[mask, "accredited_capacity_source"] = new_source
    params.to_csv(CANDIDATE_PARAMS_CSV, index=False)
    print(f"  Updated accredited_capacity_source for {mask.sum()} candidate technologies")


def plot_elcc(lookup: pd.DataFrame, resource_set: str, out_path: Path) -> None:
    """One line per technology, accredited_capacity_pct vs. year, for the given resource_set.
    Solar+Storage is dashed -- it coincides exactly with candidate Storage:Battery by
    construction (see module docstring), so both remain visible rather than one line hiding
    the other."""
    import matplotlib.pyplot as plt

    sub_all = lookup[lookup["resource_set"] == resource_set]

    with plt.rc_context({"font.family": "Times New Roman", "font.size": PLOT_FONT_SIZE}):
        fig, ax = plt.subplots(figsize=(10, 6))

        for tech in sub_all["technology"].unique():
            sub = sub_all[sub_all["technology"] == tech].sort_values("year")
            linestyle = "--" if tech == "Solar+Storage" else "-"
            ax.plot(
                sub["year"], sub["accredited_capacity_pct"],
                marker="o", markersize=4, linewidth=2, linestyle=linestyle,
                color=TECH_COLORS[tech], label=tech,
            )

        ax.set_xlabel("Year", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("Accredited Capacity (%)", fontsize=PLOT_FONT_SIZE)
        ax.set_ylim(0, 105)
        ax.tick_params(axis="both", labelsize=PLOT_TICK_LABELSIZE)
        ax.spines[["top", "right"]].set_visible(False)

        handles, labels = ax.get_legend_handles_labels()
        ax.legend(
            handles[::-1], labels[::-1],
            loc="upper left", bbox_to_anchor=(1.02, 1),
            fontsize=PLOT_FONT_SIZE, frameon=False, borderpad=0.8, labelspacing=0.5,
        )

        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    print(f"  Chart -> {out_path.name}")


def print_summary(lookup: pd.DataFrame) -> None:
    print(f"\n  elcc_lookup.csv: {len(lookup)} rows")
    n_interp = lookup["interpolated"].sum()
    print(f"  Interpolated rows: {n_interp} of {len(lookup)}")
    for resource_set in ["existing", "candidate"]:
        sub = lookup[lookup["resource_set"] == resource_set]
        print(f"\n  {resource_set.capitalize()}:")
        for tech in sub["technology"].unique():
            tsub = sub[sub["technology"] == tech].set_index("year")["accredited_capacity_pct"]
            print(f"    {tech:<16} 2026={tsub.get(2026, float('nan')):>6.2f}%  "
                  f"2030={tsub.get(2030, float('nan')):>6.2f}%  "
                  f"2040={tsub.get(2040, float('nan')):>6.2f}%  "
                  f"2050={tsub.get(2050, float('nan')):>6.2f}%")


def main() -> None:
    print("\n--- Script 24: Accredited Capacity -- ELCC (NREL Avg/Marginal Capacity Credit) ---")

    print("\n[1/5] Downloading/loading NREL capacity credit data...")
    download_if_missing(AVG_CSV, AVG_URL)
    download_if_missing(MAR_CSV, MAR_URL)

    print("\n[2/5] Computing statewide ReEDS-region weights...")
    weights = compute_statewide_weights()

    print("\n[3/5] Building ELCC lookup table...")
    lookup = build_lookup(weights)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(OUT_CSV, index=False)
    print(f"  Saved: {OUT_CSV.relative_to(PROJECT_ROOT)}  ({len(lookup)} rows)")

    print("\n[4/6] Updating accredited_capacity_source on existing/candidate resource files...")
    update_source_tags()

    print("\n[5/6] Saving diagnostic charts...")
    plot_elcc(lookup, "existing", AVG_PLOT_OUT)
    plot_elcc(lookup, "candidate", MAR_PLOT_OUT)

    print("\n[6/6] Summary...")
    print_summary(lookup)


if __name__ == "__main__":
    main()
