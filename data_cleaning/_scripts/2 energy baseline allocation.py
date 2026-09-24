import pandas as pd

# Read the Excel file, starting from the correct header row (row 4, so header=3)
file_path = r'../data_cleaning/load/raw/Sales_Ult_Cust_2024.xlsx'
import os
script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
file_path_abs = os.path.normpath(os.path.join(script_dir, '..', 'data_cleaning', 'load', 'raw', 'Sales_Ult_Cust_2024.xlsx'))
df = pd.read_excel(file_path_abs, engine='openpyxl', header=2)

# Filter for Colorado (CO) only
df_co = df[df['State'] == 'CO']

# Convert sales columns to numeric, coercing errors
df_co['Megawatthours'] = pd.to_numeric(df_co['Megawatthours'], errors='coerce') if 'Megawatthours' in df_co.columns else pd.to_numeric(df_co.iloc[:,10], errors='coerce')
df_co['Megawatthours.1'] = pd.to_numeric(df_co['Megawatthours.1'], errors='coerce') if 'Megawatthours.1' in df_co.columns else pd.to_numeric(df_co.iloc[:,13], errors='coerce')
df_co['Megawatthours.2'] = pd.to_numeric(df_co['Megawatthours.2'], errors='coerce') if 'Megawatthours.2' in df_co.columns else pd.to_numeric(df_co.iloc[:,16], errors='coerce')
df_co['Megawatthours.3'] = pd.to_numeric(df_co['Megawatthours.3'], errors='coerce') if 'Megawatthours.3' in df_co.columns else pd.to_numeric(df_co.iloc[:,19], errors='coerce')

total_residential = df_co['Megawatthours'].sum() if 'Megawatthours' in df_co.columns else df_co.iloc[:,10].sum()
total_commercial = df_co['Megawatthours.1'].sum() if 'Megawatthours.1' in df_co.columns else df_co.iloc[:,13].sum()
total_industrial = df_co['Megawatthours.2'].sum() if 'Megawatthours.2' in df_co.columns else df_co.iloc[:,16].sum()
total_transportation = df_co['Megawatthours.3'].sum() if 'Megawatthours.3' in df_co.columns else df_co.iloc[:,19].sum()
total_all = total_residential + total_commercial + total_industrial + total_transportation

print('Total Megawatthour Sales in Colorado:')
print(f'Residential: {total_residential:,.0f} MWh')
print(f'Commercial: {total_commercial:,.0f} MWh')
print(f'Industrial: {total_industrial:,.0f} MWh')
print(f'Transportation: {total_transportation:,.0f} MWh')


# --- Export total sales numbers as a table to CSV ---
import numpy as np
import pathlib
total_sales_df = pd.DataFrame({
	'Sector': ['Residential', 'Commercial', 'Industrial', 'Transportation', 'All Classes Total'],
	'Total_MWh': [
		total_residential,
		total_commercial,
		total_industrial,
		total_transportation,
		total_all
	]
})
output_path = os.path.normpath(os.path.join(script_dir, '..', 'data_cleaning', 'load', 'total_sales_CO_2024.csv'))
total_sales_df.to_csv(output_path, index=False)
print(f"\nExported total sales by sector to {output_path}")

# --- Load the "County" tab from the specified Excel workbook ---
county_file_path = os.path.normpath(os.path.join(script_dir, '..', 'data_cleaning', 'load', 'raw', '2016cityandcountyenergyprofiles_units correction.xlsb'))
# Row 5 is header, so header=4 (0-based index)
county_df = pd.read_excel(county_file_path, sheet_name='County', header=4, engine='pyxlsb')
print("\nLoaded 'County' sheet from 2016cityandcountyenergyprofiles_units correction.xlsb:")

print(county_df.head())

# Filter county_df for Colorado counties
county_co_df = county_df[county_df['state_abbr'] == 'CO']
print("\nFiltered counties for Colorado (state_abbr == 'CO'):")

print(county_co_df.head())

# Extract county name before ' County, CO' in 'county_state_name'
county_co_df['county_name'] = county_co_df['county_state_name'].str.extract(r'^(.*) County, CO$')[0]
print("\nCounty names extracted:")
print(county_co_df[['county_state_name', 'county_name']].head())
print(county_co_df[['county_state_name', 'county_name']].head())

# Colorado county-to-zone mapping
zone_county_map = {
	'Denver': ['Denver', 'Arapahoe', 'Jefferson', 'Douglas', 'Broomfield', 'Adams', 'Boulder',
			   'Gilpin', 'Clear Creek'],
	'North': ['Larimer', 'Weld', 'Morgan'],
	'South': ['El Paso', 'Pueblo', 'Fremont', 'Huerfano', 'Las Animas', 
			  'Alamosa', 'Saguache', 'Rio Grande', 'Conejos', 'Costilla', 'Mineral',
			  'Custer', 'Chaffee', 'Park', 'Teller'],
	'East': ['Logan', 'Washington', 'Kit Carson', 'Lincoln', 'Yuma', 
			 'Phillips', 'Sedgwick', 'Cheyenne', 'Kiowa', 'Crowley', 'Otero', 
			 'Bent', 'Prowers', 'Baca', 'Elbert'],
	'Mountain': ['Summit', 'Eagle', 'Pitkin', 'Grand', 'Lake', 'Jackson'],
	'West': ['Mesa', 'Montrose', 'Delta', 'Garfield', 
			 'Routt', 'Moffat', 'Rio Blanco', 'Gunnison', 
			  'La Plata', 'Archuleta', 'San Juan', 'Dolores', 'Montezuma', 
			 'San Miguel', 'Ouray', 'Hinsdale']
}

# Flatten all counties in mapping
all_mapped_counties = [county for counties in zone_county_map.values() for county in counties]

# Find unmatched counties
county_names_set = set(county_co_df['county_name'])
unmatched_counties = [county for county in all_mapped_counties if county not in county_names_set]

if unmatched_counties:
	print("\nCounties in mapping NOT found in county_co_df['county_name']:")
	print(unmatched_counties)
else:
	print("\nAll mapped counties found in county_co_df['county_name'].")

# --- Calculate sector shares by zone ---
# Map each county to its zone
county_to_zone = {}
for zone, counties in zone_county_map.items():
	for county in counties:
		county_to_zone[county] = zone

# Add a 'zone' column to county_co_df
county_co_df['zone'] = county_co_df['county_name'].map(county_to_zone)

# Define sector columns (Excel columns: O, Z, AV)
sector_cols = {
	'Residential': 'O',
	'Commercial': 'Z',
	'Industry': 'AV'
}

# Get the actual column names from the DataFrame (in case they are not single letters)
col_names = list(county_co_df.columns)
sector_col_map = {}
for sector, col_letter in sector_cols.items():
	# Excel columns are 0-indexed in pandas, so O=14, Z=25, AV=47
	if col_letter == 'O':
		sector_col_map[sector] = col_names[14]
	elif col_letter == 'Z':
		sector_col_map[sector] = col_names[25]
	elif col_letter == 'AV':
		sector_col_map[sector] = col_names[47]

# Calculate total Colorado consumption by sector (from county data for shares)
county_total_by_sector = {}
for sector, col in sector_col_map.items():
    county_total_by_sector[sector] = county_co_df[col].sum()

# Calculate zone sums and shares using county totals
zone_sector_sums = county_co_df.groupby('zone').agg({col: 'sum' for col in sector_col_map.values()})
zone_sector_shares = zone_sector_sums.copy()
for sector, col in sector_col_map.items():
    zone_sector_shares[sector] = zone_sector_sums[col] / county_total_by_sector[sector]

print("\nZone-sector shares (fraction of Colorado total by sector):")

zone_sector_shares_out = zone_sector_shares[[s for s in sector_col_map.keys()]].reset_index()
zone_sector_shares_path = os.path.normpath(os.path.join(script_dir, '..', 'data_cleaning', 'load', 'zone_sector_shares_CO_2024.csv'))
zone_sector_shares_out.to_csv(zone_sector_shares_path, index=False)
print(zone_sector_shares_out)
print(f"\nExported zone-sector shares to {zone_sector_shares_path}")
print(f"\nExported zone-sector shares to {zone_sector_shares_path}")

# --- Calculate Ehats (zonal sectoral energy estimates) ---
# Use EIA state-level totals for Ehats
eia_total_by_sector = {
    'Residential': total_residential,
    'Commercial': total_commercial,
    'Industry': total_industrial
}
ehat = zone_sector_shares[[s for s in sector_col_map.keys()]].copy()
for sector in sector_col_map.keys():
    ehat[sector] = zone_sector_shares[sector] * eia_total_by_sector[sector]

# Assign all transportation to Denver commercial sector
if 'Transportation' in total_sales_df['Sector'].values:
    total_transport = total_sales_df[total_sales_df['Sector'] == 'Transportation']['Total_MWh'].iloc[0]
else:
    total_transport = 0

# Add all transportation to Denver commercial
ehat.loc['Denver', 'Commercial'] += total_transport
ehat_out = ehat.reset_index()
ehat_path = os.path.normpath(os.path.join(script_dir, '..', 'data_cleaning', 'load', 'zone_sector_ehat_CO_2024.csv'))
ehat_out.to_csv(ehat_path, index=False)
print("\nExported zone-sector Ehats to", ehat_path)
print(ehat_out)

# Confirm each sector column sums to unity
print("\nSum of shares by sector (should be 1.0):")
for sector in sector_col_map.keys():
	col_sum = zone_sector_shares[sector].sum()
	print(f"{sector}: {col_sum:.6f}")

# --- County total annual energy (Residential + Commercial + Industrial) ---
# Ensure the three sector columns are numeric
for col in sector_col_map.values():
    county_co_df[col] = pd.to_numeric(county_co_df[col], errors='coerce').fillna(0)

# Build county totals row-wise
county_totals_df = county_co_df[[
    'county_name',
    sector_col_map['Residential'],
    sector_col_map['Commercial'],
    sector_col_map['Industry']
]].copy()

county_totals_df = county_totals_df.rename(columns={
    sector_col_map['Residential']: 'Residential_MWh',
    sector_col_map['Commercial']: 'Commercial_MWh',
    sector_col_map['Industry']: 'Industrial_MWh'
})

county_totals_df['Total_MWh'] = (
    county_totals_df['Residential_MWh']
    + county_totals_df['Commercial_MWh']
    + county_totals_df['Industrial_MWh']
)


county_totals_path = os.path.normpath(os.path.join(
    script_dir, '..', 'data_cleaning', 'load', 'county_total_energy_CO.csv'
))
county_totals_df.to_csv(county_totals_path, index=False)

print(f"\nExported county total annual energy to {county_totals_path}")
print(county_totals_df.head())


# --- EnCompass workbook export moved to encompass script 2 ---
print("\nBaseline CSV outputs complete.")
print("Run 'encompass/2 build load forecast import template.py' to generate the EnCompass import workbook.")

