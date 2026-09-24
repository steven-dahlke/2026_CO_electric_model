"""
Script 1: Build Colorado zone and transmission maps.
"""

import os
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT = find_project_root()
DATA_CLEANING_DIR = PROJECT_ROOT / "data_cleaning"
data_dir = DATA_CLEANING_DIR / "counties"
shapefile_path = data_dir / "tl_2025_us_county.shp"

# Load the shapefile
print("Loading shapefile...")
gdf = gpd.read_file(shapefile_path)

print(f"Total counties in dataset: {len(gdf)}")
print(f"\nDataframe columns: {gdf.columns.tolist()}")
print(f"\nFirst few rows:")
print(gdf.head())

# Filter for Colorado counties (STATEFP = '08')
print("\nFiltering for Colorado counties...")
colorado_counties = gdf[gdf['STATEFP'] == '08'].copy()

print(f"Colorado counties found: {len(colorado_counties)}")
print(f"\nColorado counties:")
print(colorado_counties[['NAME', 'STATEFP', 'COUNTYFP']])

# Define zone assignments
zone_mapping = {
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

# Create reverse mapping: county -> zone
county_to_zone = {}
for zone, counties in zone_mapping.items():
    for county in counties:
        county_to_zone[county] = zone

# Add zone column to dataframe
colorado_counties['ZONE'] = colorado_counties['NAME'].map(county_to_zone)

# Check for any unmapped counties
unmapped = colorado_counties[colorado_counties['ZONE'].isna()]
if len(unmapped) > 0:
    print("\nWarning: The following counties were not mapped to a zone:")
    print(unmapped[['NAME']].to_string())
else:
    print("\nAll counties successfully mapped to zones.")

# ---------------------------------------------------------------------------
# Zone -> BA assignment and planning reserve margins
# ---------------------------------------------------------------------------
# Platform-agnostic source of truth for zone-BA membership and the NERC reserve-margin
# schedule -- `encompass/scripts/1 build topology import template.py` reads these files
# instead of keeping its own hardcoded copy (fixed 2026-08-05: that copy had silently
# drifted from the correct NERC LTRA 2025 values in the project writeup's Table 2).
zones_dir = DATA_CLEANING_DIR / "zones"
zones_dir.mkdir(parents=True, exist_ok=True)

# Denver/North/South/Mountain sit in the PSCo BA; East/West sit in WACM (writeup, Topology
# section). Both BAs fall within the WECC-Rocky Mountain NERC assessment area.
zone_to_ba = {
    'Denver': 'PSCo', 'North': 'PSCo', 'South': 'PSCo', 'Mountain': 'PSCo',
    'East': 'WACM', 'West': 'WACM',
}
zone_ba_df = pd.DataFrame(zone_to_ba.items(), columns=['zone', 'BA'])
zone_ba_path = zones_dir / 'zone_ba_map.csv'
zone_ba_df.to_csv(zone_ba_path, index=False)
print(f"\nSaved zone-BA map to {zone_ba_path}")

# Reference Margin Level (%), WECC-Rocky Mountain assessment area, NERC 2025 Long-Term
# Reliability Assessment (LTRA), p.159 -- confirmed 2026-08-05 directly against the published
# table (applies to both PSCo and WACM, since both sit in the same assessment area). Native
# coverage is 2026-2035 (NERC's 10-year assessment window); 2036-2050 is flat-held at the 2035
# value per 2026-08-05 direction, pending a longer-horizon reliability source.
NERC_LTRA_2025_YEARS = list(range(2026, 2036))
NERC_LTRA_2025_PCT = [17.8, 17.0, 16.2, 16.1, 15.7, 15.2, 13.5, 11.9, 14.1, 13.9]
FLAT_HOLD_YEARS = list(range(2036, 2051))

reserve_margin_rows = []
for ba in zone_ba_df['BA'].unique():
    for year, pct in zip(NERC_LTRA_2025_YEARS, NERC_LTRA_2025_PCT):
        reserve_margin_rows.append({
            'BA': ba, 'year': year, 'reference_margin_pct': pct,
            'source': 'nerc_ltra_2025_wecc_rocky_mountain',
        })
    for year in FLAT_HOLD_YEARS:
        reserve_margin_rows.append({
            'BA': ba, 'year': year, 'reference_margin_pct': NERC_LTRA_2025_PCT[-1],
            'source': 'flat_held_from_2035',
        })

ba_reserve_margin_df = pd.DataFrame(reserve_margin_rows)
ba_reserve_margin_path = zones_dir / 'ba_reserve_margin.csv'
ba_reserve_margin_df.to_csv(ba_reserve_margin_path, index=False)
print(f"Saved BA reserve margin schedule to {ba_reserve_margin_path}")

# Dissolve counties by zone
print("\nDissolving counties into zones...")
zones = colorado_counties.dissolve(by='ZONE', aggfunc='first')

print(f"\nZones created: {len(zones)}")
print(f"\nZone summary:")
print(zones[['NAME']])

# Create a visualization with zones
print("\nGenerating zone visualization...")
# Visualization parameters (adjust these as needed)
zone_label_fontsize_zoneonly = 27  # Fine-tuned font size for first map
zone_label_fontsize = 22  # Font size for other maps
# Line width parameters (adjust these to change thickness)
linewidth_230 = 2.0
# Make 345 kV 25% thicker than 230 kV, and 500 kV 25% thicker than 345 kV
linewidth_345 = linewidth_230 * 1.5
linewidth_500 = linewidth_345 * 1.5
label_zorder = 22
# Legend parameters
legend_size = 28
legend_loc = 'middle right'  # try 'middle right', 'upper right', or use bbox_to_anchor for outside positioning

output_dir = DATA_CLEANING_DIR / "zones"
output_dir.mkdir(parents=True, exist_ok=True)

fig, ax = plt.subplots(figsize=(14, 12))

# Define colors for each zone (cool-only palette)
colors = {
    'Denver': '#2E86AB',
    'North': '#4ECDC4',
    'South': '#45B7D1',
    'East': '#6FA3D1',
    'Mountain': '#8B6BA8',
    'West': '#98D8C8'
}

# Plot each zone with its color
for zone, color in colors.items():
    if zone in zones.index:
        zone_geom = zones.loc[[zone]]
        zone_geom.plot(ax=ax, alpha=0.7, edgecolor='black', linewidth=1.5, color=color, label=zone)

# Add labels for each zone at the centroid (drawn before transmission)
for zone in zones.index:
    centroid = zones.loc[zone].geometry.centroid
    x, y = centroid.x, centroid.y
    ax.text(
        x,
        y,
        zone,
        ha='center',
        va='center',
        fontsize=zone_label_fontsize_zoneonly,
        fontweight='bold',
        color='white',
        bbox=dict(boxstyle='round,pad=0.5', facecolor=(0.25, 0.25, 0.25, 0.6), edgecolor='none'),
        transform=ax.transData,
        zorder=label_zorder,
    )

# Remove axis border and latitude/longitude ticks/labels for zone-only map
ax.set_xticks([])
ax.set_yticks([])
for spine in ax.spines.values():
    spine.set_visible(False)

# Save a version of the map with only the zones (before adding transmission)
zone_only_file = output_dir / 'colorado_zones.png'
fig.savefig(zone_only_file, dpi=150, bbox_inches='tight')
print(f"Saved zone-only figure to {zone_only_file}")

# Load transmission lines and overlay high-voltage lines (>=230 kV)
print("\nLoading transmission shapefile and filtering high-voltage lines...")
transmission_path = data_dir.parent / 'transmission' / 'Electric_Power_Transmission_Lines_A.shp'
trans_gdf = gpd.read_file(transmission_path)
print(f"Transmission columns: {trans_gdf.columns.tolist()}")
# Clip transmission to Colorado + buffer (100 miles) and filter for high-voltage
trans_gdf['VOLTAGE'] = pd.to_numeric(trans_gdf['VOLTAGE'], errors='coerce')

# Create a Colorado boundary geometry and buffer it by 100 miles (in meters)
buffer_m = 160934.4  # 100 miles in meters
colorado_boundary = gpd.GeoDataFrame(geometry=[colorado_counties.unary_union], crs=colorado_counties.crs)
colorado_3857 = colorado_boundary.to_crs(epsg=3857)
buffer_poly = colorado_3857.geometry.buffer(buffer_m).iloc[0]

# Reproject transmission data to 3857 (same units as buffer) and clip
trans_3857 = trans_gdf.to_crs(epsg=3857)
trans_clipped = gpd.clip(trans_3857, buffer_poly)
print(f"Transmission features within 100-mile buffer: {len(trans_clipped)}")

# Now filter clipped transmission for high-voltage lines
hv_lines = trans_clipped[trans_clipped['VOLTAGE'] >= 230].copy()
print(f"High-voltage (>=230 kV) lines after clipping: {len(hv_lines)}")

if len(hv_lines) > 0:
    # Reproject hv lines to zones CRS for plotting
    hv_lines = hv_lines.to_crs(zones.crs)

    # Split into two categories for visual emphasis
    hv_500 = hv_lines[hv_lines['VOLTAGE'] >= 500]
    hv_230_499 = hv_lines[(hv_lines['VOLTAGE'] >= 230) & (hv_lines['VOLTAGE'] < 500)]

    if len(hv_230_499) > 0:
        # further split 230 vs 345
        hv_230_only = hv_230_499[hv_230_499['VOLTAGE'].round().astype('Int64') == 230]
        hv_345_only = hv_230_499[hv_230_499['VOLTAGE'].round().astype('Int64') == 345]
        if len(hv_230_only) > 0:
            hv_230_only.plot(ax=ax, color='#B8860B', linewidth=linewidth_230, label='230 kV', zorder=5)
        if len(hv_345_only) > 0:
            hv_345_only.plot(ax=ax, color="#660000", linewidth=linewidth_345, label='345 kV', zorder=6)
    if len(hv_500) > 0:
        hv_500.plot(ax=ax, color='black', linewidth=linewidth_500, label='500 kV', zorder=7)

    # Add legend for transmission lines (parameterized size & location)
    handles, labels = ax.get_legend_handles_labels()
    # If user requests right-side placement, anchor the legend outside the axes for clarity
    if legend_loc in ('upper right', 'lower right', 'middle right'):
        if legend_loc == 'upper right':
            bbox = (0.98, 1)
            loc_arg = 'upper left'
        elif legend_loc == 'lower right':
            bbox = (0.98, 0)
            loc_arg = 'upper left'
        else:  # middle right
            bbox = (0.92, 0.5)
            loc_arg = 'center left'
        ax.legend(handles, labels, loc=loc_arg, bbox_to_anchor=bbox, prop={'family': 'Times New Roman', 'size': legend_size}, frameon=False)
    elif legend_loc in ('upper left', 'lower left'):
        if legend_loc == 'upper left':
            bbox = (-0.02, 1)
            loc_arg = 'lower right'
        else:
            bbox = (-0.02, 0)
            loc_arg = 'upper right'
        ax.legend(handles, labels, loc=loc_arg, bbox_to_anchor=bbox, prop={'family': 'Times New Roman', 'size': legend_size}, frameon=False)
    else:
        ax.legend(handles, labels, loc=legend_loc, prop={'family': 'Times New Roman', 'size': legend_size}, frameon=False)

# Add labels for each zone at the centroid (drawn last so they appear on top)
for zone in zones.index:
    centroid = zones.loc[zone].geometry.centroid
    x, y = centroid.x, centroid.y
    ax.text(
        x,
        y,
        zone,
        ha='center',
        va='center',
        fontsize=zone_label_fontsize,
        fontweight='bold',
        color='white',
        bbox=dict(boxstyle='round,pad=0.5', facecolor=(0.25, 0.25, 0.25, 0.6), edgecolor='none'),
        transform=ax.transData,
        zorder=label_zorder,
    )

# Remove axis border and latitude/longitude ticks/labels
ax.set_xticks([])
ax.set_yticks([])
for spine in ax.spines.values():
    spine.set_visible(False)


plt.tight_layout()

# Save the figure to the zones subfolder
output_file = output_dir / 'colorado_zones_transmission.png'
fig.savefig(output_file, dpi=150, bbox_inches='tight')
print(f"Saved figure to {output_file}")

# After plotting the zone-only and transmission maps
# Create a third map for transmission lines with voltage >=115 kV and <230 kV
fig3, ax3 = plt.subplots(figsize=(14, 12))
for zone, color in colors.items():
    if zone in zones.index:
        zone_geom = zones.loc[[zone]]
        zone_geom.plot(ax=ax3, alpha=0.7, edgecolor='black', linewidth=1.5, color=color, label=zone)
for zone in zones.index:
    centroid = zones.loc[zone].geometry.centroid
    x, y = centroid.x, centroid.y
    ax3.text(
        x,
        y,
        zone,
        ha='center',
        va='center',
        fontsize=zone_label_fontsize,
        fontweight='bold',
        color='white',
        bbox=dict(boxstyle='round,pad=0.5', facecolor=(0.25, 0.25, 0.25, 0.6), edgecolor='none'),
        transform=ax3.transData,
        zorder=label_zorder,
    )
# Remove axis border and latitude/longitude ticks/labels
ax3.set_xticks([])
ax3.set_yticks([])
for spine in ax3.spines.values():
    spine.set_visible(False)
# Filter transmission lines for >=115 kV and <230 kV
trans_115_229 = trans_clipped[(trans_clipped['VOLTAGE'] >= 115) & (trans_clipped['VOLTAGE'] < 230)]
if len(trans_115_229) > 0:
    trans_115_229 = trans_115_229.to_crs(zones.crs)
    trans_115_229.plot(ax=ax3, color='#FF8C00', linewidth=2.0, label='115-229 kV', zorder=8)
    ax3.legend(loc='lower left', prop={'family': 'Times New Roman', 'size': legend_size}, frameon=False)
third_map_file = output_dir / 'colorado_zones_transmission_115_229.png'
fig3.savefig(third_map_file, dpi=150, bbox_inches='tight')
print(f"Saved third map to {third_map_file}")

