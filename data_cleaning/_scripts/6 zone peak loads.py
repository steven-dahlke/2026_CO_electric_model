import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = find_project_root()
DATA_LOAD = PROJECT_ROOT / "data_cleaning" / "load"
shapes_path = DATA_LOAD / "load_shapes_zone_sector_2018.csv"
ehat_path   = DATA_LOAD / "zone_sector_ehat_CO_2024.csv"
output_path = DATA_LOAD / "zone_peak_loads.csv"
ferc714_path = DATA_LOAD / "ferc714_co_forecasts_2024.csv"
uz_shares_path = DATA_LOAD / "S_uz_zone_utility_shares_CO_2024.csv"
allocated_output_path = DATA_LOAD / "zone_allocated_peaks_2025.csv"

# ---------------------------------------------------------------------------
# Load inputs
# ---------------------------------------------------------------------------
shapes = pd.read_csv(shapes_path, index_col="hour")   # index: 1–8760
ehat   = pd.read_csv(ehat_path,   index_col="zone")   # cols: Residential, Commercial, Industry

zones = ehat.index.tolist()
print(f"Zones: {zones}")
print(f"Shapes columns: {shapes.columns.tolist()}")

# ---------------------------------------------------------------------------
# Build datetime index for 2018 (non-leap, MST) to tag seasons
# NERC seasons: Summer = June–September, Winter = December–March
# ---------------------------------------------------------------------------
# Hours 1–8760 map to 2018-01-01 00:00 through 2018-12-31 23:00 (hourly)
dt_index = pd.date_range("2018-01-01", periods=8760, freq="h")
months = dt_index.month                          # array of month numbers (1–12)

summer_mask = pd.Series(months).isin([6, 7, 8, 9]).values
winter_mask = pd.Series(months).isin([12, 1, 2, 3]).values

# ---------------------------------------------------------------------------
# For each zone, compute hourly load (MWh = MW at hourly resolution) as
#   L_z(h) = s_Res_z(h) * E_Res_z  +  s_Com_z(h) * E_Com_z  +  s_Ind(h) * E_Ind_z
# then find peak (max) hour in summer and winter windows.
# ---------------------------------------------------------------------------
results = []

for zone in zones:
    e_res = ehat.loc[zone, "Residential"]
    e_com = ehat.loc[zone, "Commercial"]
    e_ind = ehat.loc[zone, "Industry"]

    s_res = shapes[f"{zone}_Res"].values
    s_com = shapes[f"{zone}_Com"].values
    s_ind = shapes["Industrial"].values

    hourly_load = s_res * e_res + s_com * e_com + s_ind * e_ind  # MW

    summer_peak = hourly_load[summer_mask].max()
    winter_peak = hourly_load[winter_mask].max()

    summer_hour = hourly_load[summer_mask].argmax()
    winter_hour = hourly_load[winter_mask].argmax()

    # Recover actual calendar hour for diagnostics
    summer_dt = dt_index[summer_mask][summer_hour]
    winter_dt = dt_index[winter_mask][winter_hour]

    results.append({
        "zone":            zone,
        "summer_peak_MW":  round(summer_peak, 2),
        "summer_peak_hour": summer_dt.strftime("%Y-%m-%d %H:%M"),
        "winter_peak_MW":  round(winter_peak, 2),
        "winter_peak_hour": winter_dt.strftime("%Y-%m-%d %H:%M"),
    })

    print(f"  {zone:10s}  Summer: {summer_peak:9.1f} MW ({summer_dt})  "
          f"Winter: {winter_peak:9.1f} MW ({winter_dt})")

# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------
results_df = pd.DataFrame(results).set_index("zone")
results_df.to_csv(output_path)
print(f"\nSaved peak loads to {output_path}")
print(results_df.to_string())

# ---------------------------------------------------------------------------
# Allocate FERC 714 utility summer/winter peaks to zones using utility-zone shares
# ---------------------------------------------------------------------------
ferc714 = pd.read_csv(ferc714_path)
ferc714 = ferc714[ferc714["forecast_year"] == 2025]

uz_shares = pd.read_csv(uz_shares_path)

merged = uz_shares.merge(
    ferc714[["utility_group", "summer_peak_demand_forecast_mw", "winter_peak_demand_forecast_mw"]],
    on="utility_group", how="left"
)

# Convert zone-normalized share (s_uz) to utility-normalized share (s_zu)
# so each utility's allocated peaks sum to its original forecast.
merged["utility_total_MWh"] = merged.groupby("utility_group")["utility_zone_E_uc_MWh"].transform("sum")
merged["s_zu"] = merged["utility_zone_E_uc_MWh"] / merged["utility_total_MWh"]

merged["summer_peak_allocated"] = merged["summer_peak_demand_forecast_mw"] * merged["s_zu"]
merged["winter_peak_allocated"] = merged["winter_peak_demand_forecast_mw"] * merged["s_zu"]

zone_alloc = merged.groupby("zone").agg({
    "summer_peak_allocated": "sum",
    "winter_peak_allocated": "sum"
}).rename(columns={
    "summer_peak_allocated": "allocated_summer_peak_MW",
    "winter_peak_allocated": "allocated_winter_peak_MW"
})

zone_alloc_rounded = zone_alloc.round(2)
zone_alloc_rounded.to_csv(allocated_output_path)

print(f"\nSaved allocated zone peaks to {allocated_output_path}")
print(zone_alloc_rounded.to_string())

# ---------------------------------------------------------------------------
# Verification: Check that sum of allocated zone peaks matches sum of utility peaks
# ---------------------------------------------------------------------------
total_utility_summer = ferc714["summer_peak_demand_forecast_mw"].sum()
total_utility_winter = ferc714["winter_peak_demand_forecast_mw"].sum()
total_zone_summer = zone_alloc["allocated_summer_peak_MW"].sum()
total_zone_winter = zone_alloc["allocated_winter_peak_MW"].sum()

# Utility-level share sanity check: s_zu should sum to 1.0 for each utility
share_check = merged.groupby("utility_group")["s_zu"].sum()

print("\n--- Verification: Utility vs. Zone Peak Sums (MW) ---")
print("s_zu sum by utility (should be 1.0):")
print(share_check.to_string())
print(f"Total utility summer peak: {total_utility_summer:.2f}")
print(f"Total zone-allocated summer peak: {total_zone_summer:.2f}")
print(f"Difference: {total_zone_summer - total_utility_summer:.4f}\n")
print(f"Total utility winter peak: {total_utility_winter:.2f}")
print(f"Total zone-allocated winter peak: {total_zone_winter:.2f}")
print(f"Difference: {total_zone_winter - total_utility_winter:.4f}\n")
