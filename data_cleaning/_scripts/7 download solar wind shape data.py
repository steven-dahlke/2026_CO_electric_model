import argparse
import getpass
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

"""
Download 2018 solar and wind time series for Colorado zones from NREL developer APIs.
Solar data uses the NSRDB endpoint, and wind data uses the BC-HRRR wind toolkit endpoint
with 100m hub-height variables for utility-scale wind analysis.

This script builds its own fixed wind point defaults for the initial model.
Wind is only modeled for East, North, and South zones; Denver, Mountain,
and West are skipped for the initial wind deployment.

Raw downloads are organized under:
- `data_cleaning/solar_wind_shapes/raw/solar/` for solar raw CSVs
- `data_cleaning/solar_wind_shapes/raw/wind/` for raw BC-HRRR wind point CSVs

Finally, top-level outputs such as averaged zone wind shapes are written to
`data_cleaning/solar_wind_shapes/`.
"""

PROJECT_ROOT = find_project_root()
DATA_CLEANING = PROJECT_ROOT / "data_cleaning"
DATA_COUNTIES = DATA_CLEANING / "counties"
DATA_LOAD = DATA_CLEANING / "load"
SHAPEFILE_PATH = DATA_COUNTIES / "tl_2025_us_county.shp"
CENTROIDS_PATH = DATA_LOAD / "zone_centroids.csv"
OUTPUT_DIR = DATA_CLEANING / "solar_wind_shapes"
RAW_DIR = OUTPUT_DIR / "raw"
RAW_SOLAR_DIR = RAW_DIR / "solar"
RAW_WIND_DIR = RAW_DIR / "wind"
RAW_SOLAR_DIR.mkdir(parents=True, exist_ok=True)
RAW_WIND_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WIND_POINT_CANDIDATES_PATH = OUTPUT_DIR / "zone_wind_point_candidates.csv"
WIND_POINTS_PER_ZONE = 3

DEFAULT_ZONE_WIND_POINTS = {
    "North": [
        {"county": "Larimer/Weld", "lon": -104.063, "lat": 40.889},  
    ],
    "East": [
        {"county": "Baca/Prowers", "lon": -102.461, "lat": 37.580},
        {"county": "Prowers/Kiowa", "lon": -103.60, "lat": 38.95},
        {"county": "Logan/Yuma", "lon": -102.30, "lat": 40.15},
    ],
    "South": [
        {"county": "Pueblo", "lon":  -104.540, "lat": 38.182},
    ],
}

API_ENDPOINTS = {
    "solar": {
        "url": "https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-conus-v4-0-0-download.csv",
        "attributes": ["ghi", "dni", "dhi", "air_temperature", "wind_speed"],
        "label": "NSRDB Solar",
    },
    "wind": {
        "url": "https://developer.nlr.gov/api/wind-toolkit/v2/wind/wtk-bchrrr-v1-0-0-download.csv",
        "attributes": [
            "windspeed_100m",
            "winddirection_100m",
            "temperature_100m",
            "pressure_0m",
        ],
        "label": "NREL BC-HRRR Wind",
    },
}
DATASETS = list(API_ENDPOINTS.keys())
API_KEY_ENV = ["NSRDB_API_KEY", "DEVELOPER_NLR_API_KEY"]
API_EMAIL_ENV = ["NSRDB_API_EMAIL", "NREL_API_EMAIL"]
ENV_FILE = PROJECT_ROOT / ".env"

SECURE_NOTE = (
    "The most secure way to use credentials is via environment variables or a local .env file. "
    "If credentials are not found, this script will prompt for them interactively."
)

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

YEAR = "2018"
INTERVAL = 60
UTC = False
LEAP_DAY = False


def find_api_value(names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def load_dotenv(env_path):
    if not env_path.exists():
        return {}

    values = {}
    with env_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            values[key] = value
    return values


def set_env_if_missing(values):
    for key, value in values.items():
        if key not in os.environ or not os.environ.get(key):
            os.environ[key] = value


def prompt_for_credentials(api_key, email):
    if api_key is None and sys.stdin.isatty():
        api_key = getpass.getpass("Enter NSRDB API key: ").strip()
    if email is None and sys.stdin.isatty():
        email = input("Enter email to associate with NSRDB requests: ").strip()
    return api_key, email


def read_colorado_zones():
    if not SHAPEFILE_PATH.exists():
        raise FileNotFoundError(f"County shapefile not found: {SHAPEFILE_PATH}")

    counties = gpd.read_file(SHAPEFILE_PATH)
    colorado_counties = counties[counties["STATEFP"] == "08"].copy()
    colorado_counties["ZONE"] = colorado_counties["NAME"].map({
        county: zone for zone, counties in ZONE_MAPPING.items() for county in counties
    })

    unmapped = colorado_counties[colorado_counties["ZONE"].isna()]
    if len(unmapped) > 0:
        raise ValueError(
            f"The following Colorado counties are not mapped to a zone: {unmapped['NAME'].tolist()}"
        )

    zones = colorado_counties.dissolve(by="ZONE", aggfunc="first")
    if zones.crs is None:
        raise ValueError("County shapefile has no CRS metadata.")

    zones = zones.to_crs(epsg=4326)
    return zones


def build_zone_centroids(zones):
    centroids = zones.copy()
    projected = centroids.geometry.to_crs(epsg=3857)
    centroid_points = projected.centroid.to_crs(epsg=4326)
    centroids["lon"] = centroid_points.x
    centroids["lat"] = centroid_points.y
    centroids["wkt"] = centroids.apply(
        lambda row: f"POINT({row['lon']} {row['lat']})", axis=1,
        result_type="reduce",
    )
    index_name = centroids.index.name or "index"
    output = centroids[["lon", "lat", "wkt"]].reset_index().rename(columns={index_name: "zone"})
    output = output[["zone", "lon", "lat", "wkt"]]
    output.to_csv(CENTROIDS_PATH, index=False)
    return output


def build_zone_wind_point_candidates(zones, points_per_zone=WIND_POINTS_PER_ZONE):
    candidates = {}
    for zone in zones.index:
        if zone not in DEFAULT_ZONE_WIND_POINTS:
            continue
        points = []
        for idx, point in enumerate(DEFAULT_ZONE_WIND_POINTS[zone][:points_per_zone], start=1):
            points.append({
                "zone": zone,
                "index": idx,
                "county": point.get("county", ""),
                "lon": point["lon"],
                "lat": point["lat"],
                "wkt": f"POINT({point['lon']} {point['lat']})",
            })
        if points:
            candidates[zone] = points

    save_zone_wind_point_candidates(candidates, WIND_POINT_CANDIDATES_PATH)
    return candidates


def save_zone_wind_point_candidates(candidates, output_path):
    rows = []
    for zone, points in candidates.items():
        for point in points:
            row = {
                "zone": zone,
                "point_index": point["index"],
                "county": point.get("county", ""),
                "lon": point["lon"],
                "lat": point["lat"],
                "wkt": point["wkt"],
            }
            if "distance_m" in point:
                row["distance_m"] = point["distance_m"]
            rows.append(row)
    pd.DataFrame(rows).to_csv(output_path, index=False)


def download_zone_point_wind_data(zone, points, api_key, email, force=False):
    point_records = []
    for point in points:
        filename = f"{zone.replace(' ', '_')}_2018_wind_point{point['index']}.csv"
        output_file = RAW_WIND_DIR / filename
        url = build_request_url("wind", point["wkt"], api_key, email)
        success = download_zone_csv("wind", f"{zone}-point{point['index']}", url, output_file, force=force)
        point_records.append({
            "point": point,
            "file": output_file,
            "success": success,
        })
        time.sleep(1.1)
    return point_records


def _read_wind_point_csv(csv_path):
    with open(csv_path, "r", encoding="utf-8", errors="replace") as fh:
        first_line = fh.readline()
    header_row = 1 if first_line.startswith("SiteID,") else 0
    df = pd.read_csv(csv_path, header=header_row)
    return df


def _find_wind_speed_column(df):
    for col in df.columns:
        key = col.lower().replace(" ", "")
        if "windspeed" in key and "100m" in key:
            return col
    raise ValueError(
        "Could not find a wind speed column in the downloaded wind CSV. "
        f"Available columns: {df.columns.tolist()}"
    )


def average_wind_point_profiles(point_records, output_file):
    dfs = []
    for record in point_records:
        if not record["success"]:
            continue
        df = _read_wind_point_csv(record["file"])
        speed_col = _find_wind_speed_column(df)
        dfs.append(df[["Year", "Month", "Day", "Hour", "Minute", speed_col]].reset_index(drop=True))

    if len(dfs) == 0:
        raise ValueError("No successful wind point downloads available to average.")

    base = dfs[0].copy()
    speeds = pd.concat([df[speed_col] for df in dfs], axis=1)
    base[speed_col] = speeds.mean(axis=1)
    base.to_csv(output_file, index=False)
    return base


def build_request_url(dataset, wkt, api_key, email):
    params = {
        "api_key": api_key,
        "email": email,
        "names": YEAR,
        "interval": INTERVAL,
        "utc": str(UTC).lower(),
        "leap_day": str(LEAP_DAY).lower(),
        "attributes": ",".join(API_ENDPOINTS[dataset]["attributes"]),
        "wkt": wkt,
        "full_name": f"CO Zone {dataset.title()} Data",
        "affiliation": "Colorado Electric Model",
        "reason": f"zone-level {dataset} shape generation",
    }
    query = urllib.parse.urlencode(params, safe="(),")
    return f"{API_ENDPOINTS[dataset]['url']}?{query}"


def download_zone_csv(dataset, zone, url, output_path, force=False):
    if output_path.exists() and not force:
        print(f"[skip] {dataset} zone {zone} already exists: {output_path.name}")
        return True
    print(f"Downloading {dataset} zone {zone}: {output_path.name}")
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content = response.read()
            output_path.write_bytes(content)
            print(f"Saved {output_path}")
            return True
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode(errors="ignore")
        print(f"HTTP error for {dataset} {zone}: {exc.code} {exc.reason}\n{error_text}")
    except Exception as exc:
        print(f"Unexpected error downloading {dataset} {zone}: {exc}")
    return False


def validate_api_access(api_key, email):
    if api_key is None:
        raise EnvironmentError(
            "No NSRDB API key available. Set NSRDB_API_KEY or DEVELOPER_NLR_API_KEY in the environment, "
            "or run interactively so the script can prompt for it."
        )
    if email is None:
        raise EnvironmentError(
            "No NSRDB email available. Set NSRDB_API_EMAIL or NREL_API_EMAIL in the environment, "
            "or run interactively so the script can prompt for it."
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download 2018 solar and wind time series for Colorado zones from NREL developer APIs."
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=API_ENDPOINTS.keys(),
        default=DATASETS,
        help="Datasets to download: solar, wind, or both.",
    )
    parser.add_argument(
        "--wind-points-per-zone",
        type=int,
        default=WIND_POINTS_PER_ZONE,
        help="Number of representative wind points to use for each zone when averaging wind profiles.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help="Directory to save downloaded zone CSV files.",
    )
    parser.add_argument(
        "--redownload", action="store_true",
        help="Force fresh downloads even for zone files that already exist locally.",
    )
    return parser.parse_args()


def main():
    print(SECURE_NOTE)
    dotenv_values = load_dotenv(ENV_FILE)
    if dotenv_values:
        print(f"Loaded credentials from {ENV_FILE}")
    elif ENV_FILE.exists():
        print(f"Found {ENV_FILE} but no valid credential entries were loaded.")
    else:
        print(f"No .env file found at {ENV_FILE}; using environment variables or interactive prompt.")
    set_env_if_missing(dotenv_values)

    api_key = find_api_value(API_KEY_ENV)
    email = find_api_value(API_EMAIL_ENV)
    api_key, email = prompt_for_credentials(api_key, email)
    validate_api_access(api_key, email)

    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    zones = read_colorado_zones()
    centroids = build_zone_centroids(zones)

    print(f"Found {len(centroids)} zones and saved centroids to {CENTROIDS_PATH}")
    print(centroids.to_string(index=False))
    print(f"Downloading datasets: {', '.join(args.datasets)}")

    wind_point_candidates = None
    if "wind" in args.datasets:
        wind_point_candidates = build_zone_wind_point_candidates(zones, args.wind_points_per_zone)
        save_zone_wind_point_candidates(wind_point_candidates, WIND_POINT_CANDIDATES_PATH)
        print(f"Saved wind point candidates to {WIND_POINT_CANDIDATES_PATH}")

    summary = []
    for _, row in centroids.iterrows():
        zone = row["zone"]
        wkt = row["wkt"]

        if "solar" in args.datasets:
            output_file = RAW_SOLAR_DIR / f"{zone.replace(' ', '_')}_2018_solar.csv"
            url = build_request_url("solar", wkt, api_key, email)
            success = download_zone_csv("solar", zone, url, output_file, force=args.redownload)
            summary.append({
                "zone": zone,
                "dataset": API_ENDPOINTS["solar"]["label"],
                "file": str(output_file),
                "success": success,
            })
            time.sleep(1.1)

        if "wind" in args.datasets:
            if zone not in wind_point_candidates:
                print(f"Skipping wind download for {zone} because no fixed wind points are configured.")
                summary.append({
                    "zone": zone,
                    "dataset": f"{API_ENDPOINTS['wind']['label']} (skipped)",
                    "file": "",
                    "success": True,
                })
                continue

            point_records = download_zone_point_wind_data(
                zone, wind_point_candidates[zone], api_key, email, force=args.redownload
            )
            successful_points = [r for r in point_records if r["success"]]
            for record in point_records:
                summary.append({
                    "zone": zone,
                    "dataset": f"{API_ENDPOINTS['wind']['label']} point {record['point']['index']}",
                    "file": str(record["file"]),
                    "success": record["success"],
                })
            if successful_points:
                averaged_file = output_dir / f"{zone.replace(' ', '_')}_2018_wind_shape.csv"
                average_wind_point_profiles(successful_points, averaged_file)
                summary.append({
                    "zone": zone,
                    "dataset": "Averaged Wind Shape",
                    "file": str(averaged_file),
                    "success": True,
                })

    print("\nDownload summary:")
    for item in summary:
        print(f"- {item['dataset']} {item['zone']}: {'OK' if item['success'] else 'FAILED'} -> {item['file']}")


if __name__ == "__main__":
    main()
