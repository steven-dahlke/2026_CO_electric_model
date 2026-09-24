import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

# Set the project root directory (parent of 'code' folder)
PROJECT_ROOT = find_project_root()
print(f"Project root: {PROJECT_ROOT}")

import pandas as pd
import matplotlib.pyplot as plt

# Load the CSV file using the project root
csv_path = PROJECT_ROOT / "data_cleaning" / "load" / "raw" / "out_ferc714__respondents_with_fips.csv"
df = pd.read_csv(csv_path)

# Filter rows where report_date and state match the criteria
filtered_df = df[(df["report_date"] == "2024-01-01T00:00:00.000Z") & (df["state"] == "CO")]

# print(filtered_df)
# Print unique values in 'respondent_name_ferc714' column
# unique_respondents = filtered_df['respondent_name_ferc714'].unique()
#print("Unique respondent_name_ferc714 values:")
# print(unique_respondents)

# Load yearly planning area demand forecast data
forecast_csv_path = PROJECT_ROOT / "data_cleaning" / "load" / "raw" / "core_ferc714__yearly_planning_area_demand_forecast.csv"
forecast_df = pd.read_csv(forecast_csv_path)

# Filter for report_year == 2024 and respondent_id_ferc714 in the specified list
respondent_ids = [37, 120, 161, 124, 154]
forecast_filtered = forecast_df[(forecast_df["report_year"] == 2024) & 
                                (forecast_df["respondent_id_ferc714"].isin(respondent_ids))]

print("\nFiltered Forecast Data (2024, specific respondents):")


# Map respondent names to respondent IDs
respondent_name_mapping = {
    37: "Colorado Springs Utilities",
    120: "Platte River Power Authority",
    161: "Western Area Power Admin- Colorado- Missouri Control Area (Rocky Mtn Region)",
    124: "Public Service Company of Colorado",
    154: "Tri-State G & T Assn., Inc."
}

# Add the respondent_name_ferc714 column to forecast_filtered
forecast_filtered = forecast_filtered.copy()
forecast_filtered["respondent_name_ferc714"] = forecast_filtered["respondent_id_ferc714"].map(respondent_name_mapping)

print("\nForecast Data with Respondent Names:")
print(forecast_filtered)

# Load the respondent ID mapping file
respondent_id_csv_path = PROJECT_ROOT / "data_cleaning" / "load" / "raw" / "core_ferc714__respondent_id.csv"
respondent_id_df = pd.read_csv(respondent_id_csv_path)

# Filter for Colorado utilities being used
colorado_respondent_ids = [37, 120, 161, 124, 154]
colorado_utilities_df = respondent_id_df[respondent_id_df["respondent_id_ferc714"].isin(colorado_respondent_ids)]

print("\nColorado Utilities with EIA Codes:")
print(colorado_utilities_df[["respondent_id_ferc714", "respondent_name_ferc714", "eia_code"]])

# Load the Service Territory Excel file, sheet "Counties_States"
service_territory_path = PROJECT_ROOT / "data_cleaning" / "load" / "raw" / "Service_Territory_2024.xlsx"
service_territory_df = pd.read_excel(service_territory_path, sheet_name="Counties_States")

# Filter service territory for utility numbers of interest
utility_numbers = [3989, 15466, 27000]
service_territory_filtered = service_territory_df[service_territory_df["Utility Number"].isin(utility_numbers)]

# For utility 27000, additionally restrict to Colorado only
service_territory_27000_co = service_territory_filtered[
    (service_territory_filtered["Utility Number"] == 27000) &
    (service_territory_filtered["State"] == "CO")
]

# Combine the explicitly filtered subsets: 3989, 15466, and 27000 CO
service_territory_filtered_final = pd.concat([
    service_territory_filtered[service_territory_filtered["Utility Number"].isin([3989, 15466])],
    service_territory_27000_co
], ignore_index=True)

print("\nFiltered Service Territory Data:")
print(service_territory_filtered_final.head())  # print first few rows to verify

# Assign the grouped utility labels to the territory rows
territory_utility_map = {
    3989: "Colorado Springs Utilities",
    15466: "Public Service Company of Colorado",
    27000: "WAPA (incl. Tri-State)",
}
service_territory_filtered_final["utility_group"] = service_territory_filtered_final["Utility Number"].map(territory_utility_map)

# Keep only the relevant columns and deduplicate if any county-utility duplicates exist
territory_unique = service_territory_filtered_final[["County", "State", "utility_group"]].drop_duplicates()

# Force specific counties to WAPA coverage so they are included in utility allocation.
wapa_manual_counties = pd.DataFrame(
    {
        "County": ["Kit Carson", "Cheyenne", "San Juan"],
        "State": ["CO", "CO", "CO"],
        "utility_group": ["WAPA (incl. Tri-State)"] * 3,
    }
)
territory_unique = pd.concat([territory_unique, wapa_manual_counties], ignore_index=True).drop_duplicates()

# Nc = number of utilities with presence in each county
county_utility_counts = territory_unique.groupby("County")["utility_group"].nunique().rename("Nc")

# Join back and calculate share Su,c = 1/Nc
utility_county_shares = territory_unique.merge(county_utility_counts, on="County", how="left")
utility_county_shares["s_uc"] = 1 / utility_county_shares["Nc"]

print("\nUtility-county shares (S_u,c):")
print(utility_county_shares.head(20))

# Sort by county for output
utility_county_shares = utility_county_shares.sort_values(by=["County", "utility_group"])

# Optionally save to CSV
shares_csv_path = PROJECT_ROOT / "data_cleaning" / "load" / "utility_county_shares.csv"
utility_county_shares.to_csv(shares_csv_path, index=False)
print(f"Utility-county shares exported to: {shares_csv_path}")


# --- Estimate utility-level consumption by county: E_(u,c) = s_(u,c) * E_c ---
# Load county total energy consumption
county_energy_path = PROJECT_ROOT / "data_cleaning" / "load" / "county_total_energy_CO.csv"
county_energy_df = pd.read_csv(county_energy_path)

# Merge utility-county shares with county total energy
# utility_county_shares already in memory from above
utility_consumption = utility_county_shares.merge(
    county_energy_df,
    left_on="County",
    right_on="county_name",
    how="left"
)

# Calculate E_(u,c) = s_(u,c) * E_c
utility_consumption["E_uc"] = utility_consumption["s_uc"] * utility_consumption["Total_MWh"]

# Select relevant columns for output
utility_consumption_final = utility_consumption[[
    "utility_group",
    "County",
    "s_uc",
    "Total_MWh",
    "E_uc"
]].copy()

utility_consumption_final = utility_consumption_final.sort_values(by=["utility_group", "County"])

# Export to CSV
utility_consumption_path = PROJECT_ROOT / "data_cleaning" / "load" / "E_uc_utility_consumption_by_county.csv"
utility_consumption_final.to_csv(utility_consumption_path, index=False)

print(f"\nUtility-level consumption by county (E_u,c) exported to: {utility_consumption_path}")
print(utility_consumption_final.head(20))


# --- Calculate zonal utility consumption shares: s_(u,z) = sum(E_(u,c))/sum(E_c) for c in zone z ---
zone_county_map = {
    "Denver": ["Denver", "Arapahoe", "Jefferson", "Douglas", "Broomfield", "Adams", "Boulder",
               "Gilpin", "Clear Creek"],
    "North": ["Larimer", "Weld", "Morgan"],
    "South": ["El Paso", "Pueblo", "Fremont", "Huerfano", "Las Animas",
              "Alamosa", "Saguache", "Rio Grande", "Conejos", "Costilla", "Mineral",
              "Custer", "Chaffee", "Park", "Teller"],
    "East": ["Logan", "Washington", "Kit Carson", "Lincoln", "Yuma",
             "Phillips", "Sedgwick", "Cheyenne", "Kiowa", "Crowley", "Otero",
             "Bent", "Prowers", "Baca", "Elbert"],
    "Mountain": ["Summit", "Eagle", "Pitkin", "Grand", "Lake", "Jackson"],
    "West": ["Mesa", "Montrose", "Delta", "Garfield",
             "Routt", "Moffat", "Rio Blanco", "Gunnison",
              "La Plata", "Archuleta", "San Juan", "Dolores", "Montezuma",
             "San Miguel", "Ouray", "Hinsdale"]
}


def normalize_county_name(value):
    if pd.isna(value):
        return value
    county = str(value).strip()
    if county.lower().endswith(" county"):
        county = county[:-7]
    return county.title()


county_zone_rows = [
    {"zone": zone, "County_norm": normalize_county_name(county)}
    for zone, counties in zone_county_map.items()
    for county in counties
]
county_zone_df = pd.DataFrame(county_zone_rows)

# Attach zone to each (utility, county) E_(u,c)
utility_consumption_zonal = utility_consumption_final.copy()
utility_consumption_zonal["County_norm"] = utility_consumption_zonal["County"].apply(normalize_county_name)
utility_consumption_zonal = utility_consumption_zonal.merge(
    county_zone_df,
    how="left",
    on="County_norm",
    validate="m:1",
)

# Compute zonal denominator: sum(E_c) by zone using county_total_energy_CO.csv
county_energy_zonal = county_energy_df.copy()
county_energy_zonal["County_norm"] = county_energy_zonal["county_name"].apply(normalize_county_name)
county_energy_zonal = county_energy_zonal.merge(
    county_zone_df,
    how="left",
    on="County_norm",
    validate="m:1",
)

zone_total_energy = (
    county_energy_zonal
    .groupby("zone", as_index=False)["Total_MWh"]
    .sum()
    .rename(columns={"Total_MWh": "zone_total_MWh"})
)

# Numerator: sum(E_(u,c)) by utility_group and zone
utility_zone_energy = (
    utility_consumption_zonal
    .groupby(["utility_group", "zone"], as_index=False)["E_uc"]
    .sum()
    .rename(columns={"E_uc": "utility_zone_E_uc_MWh"})
)

# Final zonal utility shares s_(u,z)
zone_utility_shares = utility_zone_energy.merge(
    zone_total_energy,
    how="left",
    on="zone",
    validate="m:1",
)
zone_utility_shares["s_uz"] = zone_utility_shares["utility_zone_E_uc_MWh"] / zone_utility_shares["zone_total_MWh"]
zone_utility_shares = zone_utility_shares.sort_values(by=["zone", "utility_group"])

# Report any counties that did not map to a zone
unmapped_utility_counties = sorted(
    utility_consumption_zonal.loc[utility_consumption_zonal["zone"].isna(), "County"].dropna().unique().tolist()
)
unmapped_energy_counties = sorted(
    county_energy_zonal.loc[county_energy_zonal["zone"].isna(), "county_name"].dropna().unique().tolist()
)
if unmapped_utility_counties:
    print("\nWarning: Unmapped utility-consumption counties:", unmapped_utility_counties)
if unmapped_energy_counties:
    print("\nWarning: Unmapped county-energy counties:", unmapped_energy_counties)

zone_utility_shares_path = PROJECT_ROOT / "data_cleaning" / "load" / "S_uz_zone_utility_shares_CO_2024.csv"
zone_utility_shares.to_csv(zone_utility_shares_path, index=False)

print("\nZonal utility consumption shares (s_u,z):")
print(zone_utility_shares)
print(f"\nZonal utility shares exported to: {zone_utility_shares_path}")

zone_share_check = (
    zone_utility_shares
    .groupby("zone", as_index=False)["s_uz"]
    .sum()
    .rename(columns={"s_uz": "sum_s_uz"})
)
print("\nSum of s_u,z by zone (should be near 1 if utility coverage is complete):")
print(zone_share_check)




# Sort by respondent_id_ferc714 and forecast_year
forecast_filtered = forecast_filtered.sort_values(by=["respondent_id_ferc714", "forecast_year"])

# Reorder columns: move respondent_name_ferc714 to second position
cols = forecast_filtered.columns.tolist()
cols.remove("respondent_name_ferc714")
cols.insert(1, "respondent_name_ferc714")
forecast_filtered = forecast_filtered[cols]

# Aggregate by utility_group and forecast_year (sum the forecast metrics)
index_cols = [
    "summer_peak_demand_forecast_mw",
    "winter_peak_demand_forecast_mw",
    "net_demand_forecast_mwh",
]

# Map each respondent to the desired combined utility group
utility_group_map = {
    37: "Colorado Springs Utilities",
    120: "Public Service Company of Colorado",  # PRPA
    124: "Public Service Company of Colorado",  # PSCo
    154: "WAPA (incl. Tri-State)",
    161: "WAPA (incl. Tri-State)",
}
forecast_filtered["utility_group"] = forecast_filtered["respondent_id_ferc714"].map(utility_group_map)

forecast_grouped = (
    forecast_filtered
    .groupby(["utility_group", "forecast_year"], as_index=False)[index_cols]
    .sum()
)

# Reorder groups and export this consolidated forecast data to CSV
forecast_grouped = forecast_grouped.sort_values(by=["utility_group", "forecast_year"])


# --- Adjust for wholesale load transfers (2025-2026 and 2026-2027 only) ---
# PSCo and WAPA/Tri-State report declines in 2025-2026 and/or 2026-2027 due
# to wholesale customers departing to suppliers not currently filing FERC Form
# 714. Those customers remain in Colorado. Any decline over these two specific
# year transitions is added back to all subsequent years. This adjustment is
# intentionally limited to these two transitions only; declines in later years
# may reflect legitimate demand changes and should not be corrected.

adjusted_forecasts = []

for utility in forecast_grouped["utility_group"].unique():
    utility_data = (
        forecast_grouped[forecast_grouped["utility_group"] == utility]
        .sort_values("forecast_year")
        .reset_index(drop=True)
    )

    for (yr_from, yr_to) in [(2025, 2026), (2026, 2027)]:
        row_from = utility_data[utility_data["forecast_year"] == yr_from]
        row_to   = utility_data[utility_data["forecast_year"] == yr_to]
        if row_from.empty or row_to.empty:
            continue
        for col in index_cols:
            delta = max(0, row_from[col].values[0] - row_to[col].values[0])
            if delta > 0:
                utility_data.loc[utility_data["forecast_year"] >= yr_to, col] += delta

    adjusted_forecasts.append(utility_data)

forecast_grouped = pd.concat(adjusted_forecasts, ignore_index=True)

print("\nAdjusted forecast data (wholesale load transfers corrected):")
print(forecast_grouped)


# --------------------------------------------------
# Normalize forecasts per utility_group
# to 2025 = 1 for three forecast metrics.
# --------------------------------------------------

# Work with 2025-2034 horizon (as requested)
forecast_norm = forecast_grouped.copy()

# Baseline values for each utility_group in 2025
base_2025 = (
    forecast_norm[forecast_norm["forecast_year"] == 2025]
    .set_index("utility_group")[index_cols]
    .rename(columns=lambda c: f"{c}_base2025")
)

# Join baseline to each row by utility
forecast_norm = forecast_norm.merge(
    base_2025,
    how="left",
    left_on="utility_group",
    right_index=True,
    validate="m:1",
)

# Compute indexed values (2025 = 1)
for c in index_cols:
    forecast_norm[f"{c}_idx"] = forecast_norm[c] / forecast_norm[f"{c}_base2025"]

# Optional: drop helper baseline columns
forecast_norm = forecast_norm.drop(columns=[f"{c}_base2025" for c in index_cols])

print("\nNormalized forecast index values computed for each utility:")
print(forecast_norm[["utility_group", "forecast_year"] + [f"{c}_idx" for c in index_cols]].head(20))

# Optional export for indexed values
indexed_csv_path = PROJECT_ROOT / "data_cleaning" / "load" / "ferc714_co_forecasts_2024.csv"
forecast_norm.to_csv(indexed_csv_path, index=False)
print(f"Indexed data exported to: {indexed_csv_path}")


# --- Blend utility normalized forecasts into zonal load forecast indices (Eq. 5) ---
# I_(z,t) = sum_u [ s_(u,z) * I_(u,t) ]

idx_cols = [f"{c}_idx" for c in index_cols]

# Cross-join utility shares (utility x zone) with forecast indices (utility x year)
zonal_blend = zone_utility_shares[["utility_group", "zone", "s_uz"]].merge(
    forecast_norm[["utility_group", "forecast_year"] + idx_cols],
    on="utility_group",
    how="inner",
)

# Weighted contribution: s_(u,z) * I_(u,t)
for col in idx_cols:
    zonal_blend[f"{col}_weighted"] = zonal_blend["s_uz"] * zonal_blend[col]

# Sum across utilities for each zone-year pair
weighted_cols = [f"{col}_weighted" for col in idx_cols]
zonal_load_forecast_idx = (
    zonal_blend
    .groupby(["zone", "forecast_year"], as_index=False)[weighted_cols]
    .sum()
    .rename(columns={f"{col}_weighted": col for col in idx_cols})
    .sort_values(by=["zone", "forecast_year"])
)

print("\nZonal load forecast indices (I_z,t):")
print(zonal_load_forecast_idx.to_string(index=False))

zonal_idx_csv_path = PROJECT_ROOT / "data_cleaning" / "load" / "I_zt_ load_forecast_indices_CO_2024.csv"
try:
    zonal_load_forecast_idx.to_csv(zonal_idx_csv_path, index=False)
    print(f"\nZonal load forecast indices exported to: {zonal_idx_csv_path}")
except PermissionError:
    fallback_zonal_idx_csv_path = PROJECT_ROOT / "data_cleaning" / "load" / "I_zt_ load_forecast_indices_CO_2024_updated.csv"
    zonal_load_forecast_idx.to_csv(fallback_zonal_idx_csv_path, index=False)
    print(
        "\nCould not overwrite the primary zonal forecast CSV because it is locked by another program."
    )
    print(f"Zonal load forecast indices exported to fallback path: {fallback_zonal_idx_csv_path}")


# --- Plot zonal load forecast indices as faceted lines by zone ---
plot_specs = {
    "summer_peak_demand_forecast_mw_idx": {
        "label": "Summer Peak",
        "color": "#1f77b4",
    },
    "winter_peak_demand_forecast_mw_idx": {
        "label": "Winter Peak",
        "color": "#d62728",
    },
    "net_demand_forecast_mwh_idx": {
        "label": "Annual Energy",
        "color": "#2ca02c",
    },
}

plots_dir = PROJECT_ROOT / "data_cleaning" / "load"
plots_dir.mkdir(parents=True, exist_ok=True)

# --- Font size control: adjust this single value to scale all text in the plot ---
BASE_FONT_SIZE = 26

plt.rcParams["font.family"] = "Times New Roman"

zones = sorted(zonal_load_forecast_idx["zone"].unique())
n_cols = 3
n_rows = (len(zones) + n_cols - 1) // n_cols

all_metric_cols = list(plot_specs.keys())
y_min = zonal_load_forecast_idx[all_metric_cols].min().min()
y_max = zonal_load_forecast_idx[all_metric_cols].max().max()
y_pad = max((y_max - y_min) * 0.08, 0.01)

fig, axes = plt.subplots(n_rows, n_cols, figsize=(15, 4 * n_rows), sharex=True, sharey=True)
axes = axes.flatten()

for index, zone in enumerate(zones):
    ax = axes[index]
    zone_data = zonal_load_forecast_idx[zonal_load_forecast_idx["zone"] == zone]

    for metric_col, spec in plot_specs.items():
        ax.plot(
            zone_data["forecast_year"],
            zone_data[metric_col],
            marker="o",
            linewidth=2,
            markersize=4,
            color=spec["color"],
            label=spec["label"],
        )

    ax.axhline(1.0, color="#666666", linestyle="--", linewidth=1)
    ax.set_title(zone, fontsize=BASE_FONT_SIZE)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)
    ax.tick_params(axis="both", labelsize=BASE_FONT_SIZE * 0.8)
    ax.grid(True, alpha=0.3)

for index in range(len(zones), len(axes)):
    axes[index].set_visible(False)

handles, labels = axes[0].get_legend_handles_labels()
fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.98), ncol=3, frameon=False, fontsize=BASE_FONT_SIZE * 0.9)
fig.supxlabel("Forecast Year", fontsize=BASE_FONT_SIZE)
fig.supylabel("Index (2025 = 1.0)", fontsize=BASE_FONT_SIZE)
fig.tight_layout(rect=(0, 0, 1, 0.9))

facet_plot_path = plots_dir / "zonal_load_forecast_indices_faceted.png"
fig.savefig(facet_plot_path, dpi=300, bbox_inches="tight")
plt.close(fig)

print(f"Saved faceted zonal forecast plot to: {facet_plot_path}")


# --- Extend zonal forecast indices to 2050 using last-five-year growth rates ---
extension_start_year = int(zonal_load_forecast_idx["forecast_year"].max()) + 1
extension_end_year = 2050

if extension_start_year <= extension_end_year:
    historical_end_year = extension_start_year - 1
    historical_start_year = historical_end_year - 4

    extension_rows = []
    growth_rate_rows = []

    for zone in sorted(zonal_load_forecast_idx["zone"].unique()):
        zone_hist = zonal_load_forecast_idx[zonal_load_forecast_idx["zone"] == zone]

        growth_rates = {}
        for metric_col in all_metric_cols:
            start_val_series = zone_hist.loc[zone_hist["forecast_year"] == historical_start_year, metric_col]
            end_val_series = zone_hist.loc[zone_hist["forecast_year"] == historical_end_year, metric_col]

            if start_val_series.empty or end_val_series.empty:
                annual_growth = 0.0
            else:
                start_val = float(start_val_series.iloc[0])
                end_val = float(end_val_series.iloc[0])
                annual_growth = (end_val / start_val) ** (1 / 4) - 1 if start_val > 0 else 0.0

            growth_rates[metric_col] = annual_growth

        growth_rate_rows.append(
            {
                "zone": zone,
                "growth_window_start_year": historical_start_year,
                "growth_window_end_year": historical_end_year,
                **{f"{metric_col}_annual_growth": growth_rates[metric_col] for metric_col in all_metric_cols},
            }
        )

        last_year_values = {
            metric_col: float(zone_hist.loc[zone_hist["forecast_year"] == historical_end_year, metric_col].iloc[0])
            for metric_col in all_metric_cols
        }

        for year in range(extension_start_year, extension_end_year + 1):
            extension_row = {"zone": zone, "forecast_year": year}
            for metric_col in all_metric_cols:
                prev_val = last_year_values[metric_col]
                next_val = prev_val * (1 + growth_rates[metric_col])
                extension_row[metric_col] = next_val
                last_year_values[metric_col] = next_val
            extension_rows.append(extension_row)

    zonal_extension_df = pd.DataFrame(extension_rows)
    zonal_load_forecast_idx_2050 = (
        pd.concat([zonal_load_forecast_idx, zonal_extension_df], ignore_index=True)
        .sort_values(["zone", "forecast_year"])
        .reset_index(drop=True)
    )

    zonal_extended_csv_path = PROJECT_ROOT / "data_cleaning" / "load" / "I_zt_load_forecast_indices_CO_through_2050.csv"
    zonal_load_forecast_idx_2050.to_csv(zonal_extended_csv_path, index=False)

    zonal_growth_rates_path = PROJECT_ROOT / "data_cleaning" / "load" / "I_zt_load_forecast_growth_rates_last5yrs.csv"
    pd.DataFrame(growth_rate_rows).to_csv(zonal_growth_rates_path, index=False)

    print(f"Extended zonal indices exported to: {zonal_extended_csv_path}")
    print(f"Last-five-year growth rates by zone exported to: {zonal_growth_rates_path}")