"""
Script 8: Plot Colorado model zones with representative wind points.
"""

import os
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Point

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

PROJECT_ROOT = find_project_root()
DATA_CLEANING_DIR = PROJECT_ROOT / "data_cleaning"
COUNTIES_DIR = DATA_CLEANING_DIR / "counties"
SHAPEFILE_PATH = COUNTIES_DIR / "tl_2025_us_county.shp"
OUTPUT_DIR = DATA_CLEANING_DIR / "solar_wind_shapes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ZONE_MAPPING = {
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
    'West': ['Mesa', 'Montrose', 'Delta', 'Garfield', 'Routt', 'Moffat',
             'Rio Blanco', 'Gunnison', 'La Plata', 'Archuleta', 'San Juan',
             'Dolores', 'Montezuma', 'San Miguel', 'Ouray', 'Hinsdale'],
}

# Representative wind points used in the model
WIND_POINTS = {
    'East 1': {'zone': 'East', 'lon': -102.461, 'lat': 37.580},
    'East 2': {'zone': 'East', 'lon': -103.60, 'lat': 38.95},
    'East 3': {'zone': 'East', 'lon': -102.30, 'lat': 40.15},
    'North': {'zone': 'North', 'lon': -104.063, 'lat': 40.889},
    'South': {'zone': 'South', 'lon': -104.540, 'lat': 38.182},
}

ZONE_COLORS = {
    'Denver': '#2E86AB',
    'North': '#4ECDC4',
    'South': '#45B7D1',
    'East': '#6FA3D1',
    'Mountain': '#8B6BA8',
    'West': '#98D8C8',
}


def build_colorado_zones():
    counties = gpd.read_file(SHAPEFILE_PATH)
    colorado_counties = counties[counties['STATEFP'] == '08'].copy()
    county_to_zone = {county: zone for zone, counties in ZONE_MAPPING.items() for county in counties}
    colorado_counties['ZONE'] = colorado_counties['NAME'].map(county_to_zone)
    unmapped = colorado_counties[colorado_counties['ZONE'].isna()]
    if len(unmapped) > 0:
        raise ValueError(f"Unmapped Colorado counties: {unmapped['NAME'].tolist()}")
    zones = colorado_counties.dissolve(by='ZONE', aggfunc='first')
    zones = zones.to_crs(epsg=4326)
    return zones


def build_wind_points_gdf():
    records = []
    for label, info in WIND_POINTS.items():
        records.append({
            'label': label,
            'zone': info['zone'],
            'geometry': Point(info['lon'], info['lat']),
        })
    return gpd.GeoDataFrame(records, crs='EPSG:4326')


def plot_zones_with_wind_points(zones, wind_gdf):
    fig, ax = plt.subplots(figsize=(14, 12))
    for zone, color in ZONE_COLORS.items():
        if zone in zones.index:
            zones.loc[[zone]].plot(ax=ax, color=color, edgecolor='black', linewidth=1.2, alpha=0.75, label=zone)

    # Plot wind points
    wind_gdf.plot(ax=ax, color='red', marker='o', markersize=240, edgecolor='black', linewidth=0.7, zorder=10)

    ax.set_axis_off()

    output_path = OUTPUT_DIR / 'colorado_zones_with_wind_points.png'
    fig.savefig(output_path, dpi=200, bbox_inches='tight')
    print(f"Saved map to {output_path}")


def main():
    zones = build_colorado_zones()
    wind_gdf = build_wind_points_gdf()
    plot_zones_with_wind_points(zones, wind_gdf)


if __name__ == '__main__':
    main()
