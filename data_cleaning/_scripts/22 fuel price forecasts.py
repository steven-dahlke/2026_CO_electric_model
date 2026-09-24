"""
Script 22: Fuel Price Forecasts

Builds fuel_price_lookup.csv -- a fuel-type-keyed reference table of fuel price trajectories
(2022-2050), and populates a new `Fuel` column on colorado_resources.csv (existing fleet) and
candidate_technology_parameters.csv (candidates), the join key against the lookup table.

Does NOT compute marginal_cost (fuel_price / efficiency) -- that combination happens at the
future PyPSA-network-build step, keeping this table a pure, single-purpose fuel-price reference,
same pattern as every prior script in this pipeline (one well-scoped output, combined only at
final consumption).

Source: U.S. EIA Annual Energy Outlook 2026 (AEO2026, released April 2026), scenario `cb2026`
("Counterfactual Baseline" -- confirmed this is simply AEO2026's renamed Reference case, EIA's
standard primary scenario, not an alternate/policy case).
URL base: https://www.eia.gov/outlooks/aeo/

4 fuel types needed (verified against colorado_resources.csv's energy_source column, not
TechType alone -- this caught a real, non-obvious split: 5 of 6 Gas:IC resources are actually
diesel-fueled (DFO), not gas):
  - natural_gas: Table 63 "Natural Gas Delivered Prices by End-Use Sector and Census Division"
    (suptab_63.xlsx), Electric Power sector, MOUNTAIN census division (row NDP000:ea_Mountain)
    -- real regional specificity exists and matters for gas, the dominant fuel in this model.
    Native units: 2025$/thousand cubic feet (Mcf).
  - coal, distillate_fuel_oil, uranium: Table 3 "Energy Prices by Sector and Source"
    (aeotab3.xlsx), Electric Power sector block, NATIONAL. No electric-power-sector regional
    breakdown exists for these in AEO2026 -- checked directly: Table 65 (coal) only has
    minemouth price by *supply* region (Appalachia/Interior/West), not delivered price by
    demand region; Table 57 (petroleum) only covers transportation diesel and residential
    heating oil, not electric power at all. National Table 3 is the only source that actually
    has an Electric-Power-sector line for all three, already in consistent $/MMBtu units
    (row IDs PRC000:ga_DistillateFue, PRC000:ga_SteamCoal, PRC000:ga_uranium).
  - Sanity-checked natural gas conversion against real current benchmarks (2026-08-04):
    $3.80/Mcf / 1.037 MMBtu/Mcf = $3.66/MMBtu, close to EIA's own projected 2026 average Henry
    Hub price (~$3.70/MMBtu) -- reasonable given Table 63's figure is a delivered price
    (transport/basis included) rather than a Henry Hub spot quote.

Unit normalization: all four fuels stored as price_per_mmbtu, a deliberate deviation from the
"keep native units, convert downstream" pattern used for ATB heat rate elsewhere in this
pipeline -- here we're synthesizing two EIA tables with genuinely different native units (Mcf
for gas vs. already-MMBtu for the rest), so normalizing at storage time avoids a mixed-unit
table. price_native/native_unit are kept alongside so nothing is lost.

Row lookup uses each table's stable row-identifier code (column A, e.g. "NDP000:ea_Mountain"),
not hardcoded row numbers -- robust to EIA reformatting the sheet layout in a future release.

Year coverage: AEO2026 natively covers 2025-2050. 2022-2024 are backfilled with the flat 2025
value (per 2026-08-04 direction -- those years predate a likely 2030 model start anyway, so
exact historical accuracy for them doesn't matter; the backfill just keeps year coverage
consistent with atb_candidate_lookup.csv, which starts 2022).

Fuel column mapping (existing fleet, by TechType + energy_source; candidates, by tech_class):
  Coal -> coal
  Gas:CC, Gas:CT, Gas:ST -> natural_gas
  Gas:IC -> natural_gas (energy_source=NG) or distillate_fuel_oil (energy_source=DFO)
  Hydro, Hydro:Pumped, Solar:PV, Wind, Storage:Battery -> blank (no fuel)
  Candidate Gas:CT, Gas:CC -> natural_gas; Candidate Nuclear:SMR -> uranium; others -> blank
"""

import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd
import openpyxl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT  = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"

RESOURCES_CSV    = DATA_CLEANING / "resources" / "colorado_resources.csv"
CANDIDATE_PARAMS = DATA_CLEANING / "resources" / "candidate_technology_parameters.csv"
OUT_CSV          = DATA_CLEANING / "resources" / "costs" / "fuel_price_lookup.csv"

RAW_DIR   = DATA_CLEANING / "resources" / "costs" / "eia_aeo" / "raw"
GAS_XLSX  = RAW_DIR / "suptab_63.xlsx"
GAS_URL   = "https://www.eia.gov/outlooks/aeo/supplement/excel/suptab_63.xlsx"
NAT_XLSX  = RAW_DIR / "aeotab3.xlsx"
NAT_URL   = "https://www.eia.gov/outlooks/aeo/excel/aeotab3.xlsx"

SCENARIO       = "cb2026"   # AEO2026 Counterfactual Baseline = renamed Reference case
YEARS          = list(range(2022, 2051))
NATIVE_YEARS   = list(range(2025, 2051))   # AEO2026's actual coverage; 2022-2024 backfilled
BACKFILL_YEARS = [2022, 2023, 2024]
MCF_TO_MMBTU   = 1.037   # EIA standard average heat content, natural gas

# (fuel_type, source file, row ID code, native unit, region, source citation)
FUEL_ROW_SPEC: dict[str, dict] = {
    "natural_gas": {
        "file": "gas", "row_id": "NDP000:ea_Mountain", "native_unit": "$/Mcf",
        "region": "Mountain",
        "source": "EIA AEO2026 Table 63, Electric Power sector, Mountain census division",
    },
    "coal": {
        "file": "nat", "row_id": "PRC000:ga_SteamCoal", "native_unit": "$/MMBtu",
        "region": "National",
        "source": "EIA AEO2026 Table 3, Electric Power sector, Steam Coal, national",
    },
    "distillate_fuel_oil": {
        "file": "nat", "row_id": "PRC000:ga_DistillateFue", "native_unit": "$/MMBtu",
        "region": "National",
        "source": "EIA AEO2026 Table 3, Electric Power sector, Distillate Fuel Oil, national",
    },
    "uranium": {
        "file": "nat", "row_id": "PRC000:ga_uranium", "native_unit": "$/MMBtu",
        "region": "National",
        "source": "EIA AEO2026 Table 3, Electric Power sector, Nuclear Fuel, national",
    },
}

# TechType -> fuel_type for the existing fleet; Gas:IC is resolved per-resource via energy_source.
EXISTING_FUEL_MAP: dict[str, str] = {
    "Coal":   "coal",
    "Gas:CC": "natural_gas",
    "Gas:CT": "natural_gas",
    "Gas:ST": "natural_gas",
}
GAS_IC_ENERGY_SOURCE_MAP: dict[str, str] = {
    "NG":  "natural_gas",
    "DFO": "distillate_fuel_oil",
}

CANDIDATE_FUEL_MAP: dict[str, str] = {
    "Gas:CT":      "natural_gas",
    "Gas:CC":      "natural_gas",
    "Nuclear:SMR": "uranium",
}

# Chart style -- matches Script 20's candidate CAPEX/O&M charts exactly (Times New Roman,
# same font sizes, legend outside frame, top/right spines removed).
PLOT_OUT             = DATA_CLEANING / "resources" / "costs" / "fuel_price_forecasts.png"
PLOT_FONT_SIZE       = 30   # axis titles, legend -- larger than the candidate charts since
PLOT_TICK_LABELSIZE  = 27   # this one carries less information and will be published smaller

# Colors reused from Script 14's TECH_COLORS where a fuel has an obvious existing-fleet
# counterpart (coal, nuclear); new colors picked for the two without one.
FUEL_COLORS: dict[str, str] = {
    "natural_gas":         "#455A64",   # reused from Script 14's Gas:CC
    "coal":                "#5C4033",   # reused from Script 14's Coal
    "distillate_fuel_oil": "#E6AB02",   # new -- amber, evocative of oil
    "uranium":             "#762A83",   # reused from Script 14's Nuclear
}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_if_missing(path: Path, url: str) -> Path:
    if path.exists():
        print(f"  Cached: {path.name}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {path.name} from EIA...")
    urllib.request.urlretrieve(url, path)
    print(f"  Saved: {path.name} ({path.stat().st_size / 1024:.0f} KB)")
    return path


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _find_row_by_id(ws, row_id: str) -> list:
    """Scan every cell (not just column A -- these sheets have a leading blank column) for the
    given row-identifier code; return the full row values."""
    for row in ws.iter_rows(values_only=True):
        if row and row_id in row:
            return list(row)
    raise ValueError(f"Row ID {row_id!r} not found in sheet {ws.title!r}")


def _find_year_header(ws) -> dict[int, int]:
    """Returns {column_index: year} for the first row containing a run of sequential
    year-like integers (e.g. 2025, 2026, 2027...) -- doesn't assume which column they start in,
    since these sheets have a leading blank column before the label."""
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        year_cols = {
            i: int(v) for i, v in enumerate(row)
            if isinstance(v, (int, float)) and 2020 <= v <= 2060
        }
        # Require a real run of consecutive years, not a stray single numeric cell.
        if len(year_cols) >= 5:
            cols = sorted(year_cols)
            if all(year_cols[cols[k + 1]] == year_cols[cols[k]] + 1 for k in range(len(cols) - 1)):
                return year_cols
    raise ValueError(f"Could not find a year header row in sheet {ws.title!r}")


def extract_native_series(xlsx_path: Path, row_id: str) -> dict[int, float]:
    """Returns {year: native_value} for the given row ID, using the sheet's own year header
    row rather than assuming a fixed column offset."""
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb[wb.sheetnames[0]]

    year_cols = _find_year_header(ws)
    row       = _find_row_by_id(ws, row_id)

    series = {}
    for col_idx, year in year_cols.items():
        if year not in NATIVE_YEARS or col_idx >= len(row):
            continue
        val = row[col_idx]
        if isinstance(val, (int, float)):
            series[year] = float(val)

    missing = set(NATIVE_YEARS) - set(series)
    if missing:
        raise ValueError(f"Row {row_id!r} in {xlsx_path.name} missing years: {sorted(missing)}")
    return series


def build_fuel_price_lookup(gas_xlsx: Path, nat_xlsx: Path) -> pd.DataFrame:
    rows = []
    for fuel_type, spec in FUEL_ROW_SPEC.items():
        xlsx = gas_xlsx if spec["file"] == "gas" else nat_xlsx
        native_series = extract_native_series(xlsx, spec["row_id"])

        for year in YEARS:
            lookup_year = year if year in NATIVE_YEARS else 2025   # backfill 2022-2024
            native_val  = native_series[lookup_year]

            price_per_mmbtu = (
                native_val / MCF_TO_MMBTU if spec["native_unit"] == "$/Mcf" else native_val
            )

            rows.append({
                "fuel_type":        fuel_type,
                "year":             year,
                "price_per_mmbtu":  round(price_per_mmbtu, 4),
                "price_native":     round(native_val, 4),
                "native_unit":      spec["native_unit"],
                "region":           spec["region"],
                "source":           spec["source"],
                "scenario":         SCENARIO,
            })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Fuel column enrichment
# ---------------------------------------------------------------------------

def add_fuel_column_existing(resources: pd.DataFrame) -> pd.DataFrame:
    resources = resources.copy()
    resources["Fuel"] = resources["TechType"].map(EXISTING_FUEL_MAP)

    ic_mask = resources["TechType"] == "Gas:IC"
    resources.loc[ic_mask, "Fuel"] = resources.loc[ic_mask, "energy_source"].map(
        GAS_IC_ENERGY_SOURCE_MAP
    )
    return resources


def add_fuel_column_candidates(params: pd.DataFrame) -> pd.DataFrame:
    params = params.copy()
    params["Fuel"] = params["tech_class"].map(CANDIDATE_FUEL_MAP)
    return params


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(lookup: pd.DataFrame, resources: pd.DataFrame, params: pd.DataFrame) -> None:
    print(f"\n  fuel_price_lookup.csv: {len(lookup)} rows ({lookup['fuel_type'].nunique()} fuels x {lookup['year'].nunique()} years)")
    print(f"\n  {'fuel_type':<20} {'region':<10} {'2025':>8} {'2030':>8} {'2050':>8}  (all $/MMBtu)")
    print(f"  {'-'*66}")
    for fuel_type in FUEL_ROW_SPEC:
        sub = lookup[lookup["fuel_type"] == fuel_type].set_index("year")["price_per_mmbtu"]
        region = lookup[lookup["fuel_type"] == fuel_type]["region"].iloc[0]
        print(f"  {fuel_type:<20} {region:<10} {sub.loc[2025]:>8.2f} {sub.loc[2030]:>8.2f} {sub.loc[2050]:>8.2f}")

    backfill_ok = all(
        lookup[(lookup["fuel_type"] == ft) & (lookup["year"].isin(BACKFILL_YEARS))]["price_per_mmbtu"].eq(
            lookup[(lookup["fuel_type"] == ft) & (lookup["year"] == 2025)]["price_per_mmbtu"].iloc[0]
        ).all()
        for ft in FUEL_ROW_SPEC
    )
    print(f"\n  2022-2024 backfilled flat to 2025 value: {'OK' if backfill_ok else 'MISMATCH'}")

    print(f"\n  colorado_resources.csv Fuel column:")
    print(resources["Fuel"].value_counts(dropna=False).to_string())

    print(f"\n  candidate_technology_parameters.csv Fuel column:")
    print(params[["tech_class", "Fuel"]].to_string(index=False))


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

PLOT_FUEL_TYPES = ["natural_gas", "coal", "uranium"]   # DFO excluded -- ~$26/MMBtu dwarfs the rest


def plot_fuel_prices(lookup: pd.DataFrame, out_path: Path) -> None:
    """One line per fuel_type, natural gas/coal/uranium only. Distillate fuel oil (~$20-26/MMBtu)
    is excluded -- it dwarfs the other three (all under $6/MMBtu) on a linear axis and only
    fuels 5 small diesel IC units (52 MW total), so it's not worth the visual trade-off here."""
    import matplotlib.pyplot as plt

    with plt.rc_context({"font.family": "Times New Roman", "font.size": PLOT_FONT_SIZE}):
        fig, ax = plt.subplots(figsize=(10, 6))

        for fuel_type in PLOT_FUEL_TYPES:
            sub = lookup[lookup["fuel_type"] == fuel_type].sort_values("year")
            ax.plot(
                sub["year"], sub["price_per_mmbtu"],
                linewidth=5,
                color=FUEL_COLORS[fuel_type], label=fuel_type.replace("_", " ").title(),
            )

        ax.set_xlabel("Year", fontsize=PLOT_FONT_SIZE)
        ax.set_ylabel("Fuel Price ($/MMBtu)", fontsize=PLOT_FONT_SIZE)
        ax.tick_params(axis="both", labelsize=PLOT_TICK_LABELSIZE)
        ax.spines[["top", "right"]].set_visible(False)

        handles, labels = ax.get_legend_handles_labels()
        ax.legend(
            handles, labels,
            loc="upper left",
            bbox_to_anchor=(1.02, 1),
            fontsize=PLOT_FONT_SIZE,
            frameon=False,
            borderpad=0.8,
            labelspacing=0.5,
        )

        fig.tight_layout()
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    print(f"  Chart -> {out_path.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n--- Script 22: Fuel Price Forecasts (EIA AEO2026) ---")

    print("\n[1/4] Downloading/loading EIA AEO2026 source tables...")
    gas_xlsx = download_if_missing(GAS_XLSX, GAS_URL)
    nat_xlsx = download_if_missing(NAT_XLSX, NAT_URL)

    print("\n[2/4] Building fuel_price_lookup.csv...")
    lookup = build_fuel_price_lookup(gas_xlsx, nat_xlsx)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(OUT_CSV, index=False)
    print(f"  Saved: {OUT_CSV.relative_to(PROJECT_ROOT)}  ({len(lookup)} rows)")

    print("\n[3/4] Adding Fuel column to colorado_resources.csv...")
    resources = pd.read_csv(RESOURCES_CSV)
    resources = add_fuel_column_existing(resources)
    resources.to_csv(RESOURCES_CSV, index=False)
    print(f"  Updated: {RESOURCES_CSV.name}")

    print("\n[4/4] Adding Fuel column to candidate_technology_parameters.csv...")
    params = pd.read_csv(CANDIDATE_PARAMS)
    params = add_fuel_column_candidates(params)
    params.to_csv(CANDIDATE_PARAMS, index=False)
    print(f"  Updated: {CANDIDATE_PARAMS.name}")

    print_summary(lookup, resources, params)

    print("\nSaving diagnostic chart...")
    plot_fuel_prices(lookup, PLOT_OUT)


if __name__ == "__main__":
    main()
