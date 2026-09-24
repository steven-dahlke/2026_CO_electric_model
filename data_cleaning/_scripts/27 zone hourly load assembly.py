"""
Script 27: Zone Hourly Load Assembly

Combines three already-existing, deliberately decomposed data_cleaning/load/ outputs into one
new, genuinely model-agnostic output: absolute hourly MW load for the 2025 base year, at both
the zone-sector level and the zone-aggregate level. Shared input for both the EnCompass and
PyPSA model builds (and any future platform) -- see data_cleaning/load/load_assembly_workplan.md
for the full design rationale and downstream-consumer notes.

This is the same computation encompass/scripts/2 build load forecast import template.py already
does inline (lines ~90-216) to build its own import workbook -- centralized here so the math
lives in exactly one place instead of being re-derived per platform. Only the packaging differs;
see that script for the historical reference implementation this one mirrors.

Reads:
    data_cleaning/load/load_shapes_zone_sector_2018.csv
        Hourly shape (hour 1-8760, fraction of annual energy), columns {Zone}_Res, {Zone}_Com
        per zone, plus one shared Industrial column (industrial load doesn't vary much
        diurnally by geography, so a single statewide shape is used for every zone).
    data_cleaning/load/zone_sector_ehat_CO_2024.csv
        Base-year (2024) zone-sector annual energy (MWh), columns zone, Residential,
        Commercial, Industry.
    data_cleaning/load/I_zt_load_forecast_indices_CO_through_2050.csv
        Used only to pull each zone's net_demand_forecast_mwh_idx at forecast_year == 2025, to
        align the 2024 raw energy data to the formal 2025 base year (2025's index is ~1.0).

Computation, per zone-sector:
    energy_2025_mwh = zone_sector_ehat[sector] * net_demand_forecast_mwh_idx(zone, 2025)
    hourly_mw[hour] = shape[hour] * energy_2025_mwh   (fraction-of-annual-MWh -> MW, since each
                                                         interval is 1 hour)
Zone aggregate is the sum of that zone's three sector columns.

Base year only (2025), not the full 2025-2050 projection: scaling to any other year is a one-line
scalar multiply by that year's zone growth index, trivial enough to leave to each consuming
platform rather than materializing ~1.3M rows that would just be the same base series times a
scalar.

Sector level is kept (not collapsed straight to zone totals) even though today's growth index is
zone-level only, with no sector breakdown -- costs nothing extra to output (same computation
produces both), and stays forward-compatible with sector-differentiated load growth (e.g.
electrification scenarios) if that becomes relevant for this decarbonization-pathways study.

Output: data_cleaning/load/zone_sector_hourly_load_mw_2025.csv -- hour (1-8760) index, columns
{Zone}_Res_mw / {Zone}_Com_mw / {Zone}_Ind_mw per zone (18 columns) plus {Zone}_mw zone-aggregate
columns (6 columns).
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT = find_project_root()
LOAD_DIR = PROJECT_ROOT / "data_cleaning" / "load"

SHAPES_PATH = LOAD_DIR / "load_shapes_zone_sector_2018.csv"
ENERGY_PATH = LOAD_DIR / "zone_sector_ehat_CO_2024.csv"
GROWTH_PATH = LOAD_DIR / "I_zt_load_forecast_indices_CO_through_2050.csv"
OUT_CSV = LOAD_DIR / "zone_sector_hourly_load_mw_2025.csv"

BASE_YEAR = 2025

SECTORS = ["Residential", "Commercial", "Industry"]
SECTOR_SUFFIX = {"Residential": "Res", "Commercial": "Com", "Industry": "Ind"}
# Industrial shape is shared across zones (single "Industrial" column); Res/Com shapes are
# zone-specific.
SHAPE_COLUMN = {
    "Residential": "{zone}_Res",
    "Commercial": "{zone}_Com",
    "Industry": "Industrial",
}


def load_inputs():
    shapes_df = pd.read_csv(SHAPES_PATH, index_col="hour")
    energy_df = pd.read_csv(ENERGY_PATH)
    growth_df = pd.read_csv(GROWTH_PATH)
    return shapes_df, energy_df, growth_df


def base_year_energy_mwh(energy_df: pd.DataFrame, growth_df: pd.DataFrame, zone: str, sector: str) -> float:
    """2024 zone-sector annual energy (MWh) scaled to the formal 2025 base year via that zone's
    2025 net-demand growth index -- mirrors encompass/scripts/2's energy_2025_mwh."""
    base_mwh = float(energy_df.loc[energy_df["zone"] == zone, sector].iloc[0])
    idx_2025 = float(
        growth_df.loc[
            (growth_df["zone"] == zone) & (growth_df["forecast_year"] == BASE_YEAR),
            "net_demand_forecast_mwh_idx",
        ].iloc[0]
    )
    return base_mwh * idx_2025


def build_hourly_load_mw(shapes_df: pd.DataFrame, energy_df: pd.DataFrame, growth_df: pd.DataFrame) -> pd.DataFrame:
    zones = energy_df["zone"].tolist()
    result = pd.DataFrame(index=shapes_df.index)
    result.index.name = "hour"

    for zone in zones:
        sector_cols = []
        for sector in SECTORS:
            shape_col = SHAPE_COLUMN[sector].format(zone=zone)
            energy_mwh = base_year_energy_mwh(energy_df, growth_df, zone, sector)
            out_col = f"{zone}_{SECTOR_SUFFIX[sector]}_mw"
            result[out_col] = shapes_df[shape_col] * energy_mwh
            sector_cols.append(out_col)
        result[f"{zone}_mw"] = result[sector_cols].sum(axis=1)

    return result


def verify(result: pd.DataFrame, energy_df: pd.DataFrame, growth_df: pd.DataFrame) -> None:
    assert len(result) == 8760, f"Expected 8760 hourly rows, got {len(result)}"

    for zone in energy_df["zone"].tolist():
        sector_cols = [f"{zone}_{SECTOR_SUFFIX[s]}_mw" for s in SECTORS]

        recomputed_agg = result[sector_cols].sum(axis=1)
        max_diff = (recomputed_agg - result[f"{zone}_mw"]).abs().max()
        assert max_diff < 1e-9, (
            f"{zone}: aggregate column does not match sum of its sector columns "
            f"(max diff {max_diff})"
        )

        annual_mwh = result[f"{zone}_mw"].sum()  # 1-hour intervals -> MWh == MW summed
        expected_mwh = sum(base_year_energy_mwh(energy_df, growth_df, zone, s) for s in SECTORS)
        rel_err = abs(annual_mwh - expected_mwh) / expected_mwh
        assert rel_err < 1e-6, (
            f"{zone}: annual sum {annual_mwh:,.1f} MWh does not match expected "
            f"{expected_mwh:,.1f} MWh (rel. error {rel_err:.2%})"
        )


def main() -> None:
    print("\n--- Script 27: Zone Hourly Load Assembly ---")

    print("\n[1/3] Loading inputs...")
    shapes_df, energy_df, growth_df = load_inputs()
    print(f"  Shapes: {SHAPES_PATH.name} ({len(shapes_df)} hours)")
    print(f"  Base energy: {ENERGY_PATH.name} ({len(energy_df)} zones)")
    print(f"  Growth index: {GROWTH_PATH.name}")

    print(f"\n[2/3] Building {BASE_YEAR} base-year absolute hourly load...")
    result = build_hourly_load_mw(shapes_df, energy_df, growth_df)

    print("\n[3/3] Verifying and saving...")
    verify(result, energy_df, growth_df)
    LOAD_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_CSV)
    print(f"  Saved: {OUT_CSV.relative_to(PROJECT_ROOT)} ({len(result)} rows, {len(result.columns)} columns)")

    print(f"\nSummary (annual energy by zone, {BASE_YEAR}, GWh):")
    for zone in energy_df["zone"].tolist():
        annual_gwh = result[f"{zone}_mw"].sum() / 1000.0
        print(f"  {zone:10s}: {annual_gwh:>10,.1f} GWh")


if __name__ == "__main__":
    main()
