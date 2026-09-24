import argparse
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

"""
Script 11: Download long-term average (LTA) source data for calibrating 2018 AMY profiles.

Solar  — NSRDB GOES TMY PSM v4 (names=tmy-2024), one file per zone centroid (6 files).
         Uses a separate TMY endpoint from the AMY data in script 10.

Wind   — BC-HRRR for years 2015-2023 excluding 2018 (already downloaded by script 7), five
         representative points per zone (8 years x 5 points = 40 files).

Zone centroids are read from data_cleaning/load/zone_centroids.csv (written by script 10).
Wind points are the same fixed coordinates used in script 10.

Credentials: read from .env or environment variables (same keys as script 10):
  NSRDB_API_KEY or DEVELOPER_NLR_API_KEY
  NSRDB_API_EMAIL or NREL_API_EMAIL

Output files:
  data_cleaning/solar_wind_shapes/raw/solar/{Zone}_tmy_solar.csv  (6 files)
  data_cleaning/solar_wind_shapes/raw/wind/{Zone}_{year}_wind_point{n}.csv  (40 files)
"""

PROJECT_ROOT   = find_project_root()
DATA_CLEANING  = PROJECT_ROOT / "data_cleaning"
CENTROIDS_PATH = DATA_CLEANING / "load" / "zone_centroids.csv"
RAW_SOLAR_DIR  = DATA_CLEANING / "solar_wind_shapes" / "raw" / "solar"
RAW_WIND_DIR   = DATA_CLEANING / "solar_wind_shapes" / "raw" / "wind"
ENV_FILE       = PROJECT_ROOT / ".env"

# BC-HRRR years to download — 2018 is already present from script 10
WIND_YEARS = [2015, 2016, 2017, 2019, 2020, 2021, 2022, 2023]

# Fixed wind representative points (same as script 10 DEFAULT_ZONE_WIND_POINTS)
WIND_POINTS = {
    "North": [
        {"index": 1, "lat": 40.889, "lon": -104.063},
    ],
    "East": [
        {"index": 1, "lat": 37.580, "lon": -102.461},
        {"index": 2, "lat": 38.950, "lon": -103.600},
        {"index": 3, "lat": 40.150, "lon": -102.300},
    ],
    "South": [
        {"index": 1, "lat": 38.182, "lon": -104.540},
    ],
}

SOLAR_TMY_URL = (
    "https://developer.nlr.gov/api/nsrdb/v2/solar/"
    "nsrdb-GOES-tmy-v4-0-0-download.csv"
)
SOLAR_TMY_NAME = "tmy-2024"
SOLAR_ATTRIBUTES = "ghi,dni,dhi,air_temperature,wind_speed"

WIND_URL = (
    "https://developer.nlr.gov/api/wind-toolkit/v2/wind/"
    "wtk-bchrrr-v1-0-0-download.csv"
)
WIND_ATTRIBUTES = "windspeed_100m,winddirection_100m,temperature_100m,pressure_0m"

API_KEY_NAMES   = ["NSRDB_API_KEY", "DEVELOPER_NLR_API_KEY"]
API_EMAIL_NAMES = ["NSRDB_API_EMAIL", "NREL_API_EMAIL"]


# ---------------------------------------------------------------------------
# Credential helpers (mirrors script 10)
# ---------------------------------------------------------------------------

def load_dotenv(env_path: Path) -> dict:
    if not env_path.exists():
        return {}
    values = {}
    with env_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def find_env_value(names: list[str]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def load_credentials() -> tuple[str, str]:
    dotenv = load_dotenv(ENV_FILE)
    for k, v in dotenv.items():
        if k not in os.environ:
            os.environ[k] = v

    api_key = find_env_value(API_KEY_NAMES)
    email   = find_env_value(API_EMAIL_NAMES)

    if api_key is None:
        raise EnvironmentError(
            "No API key found. Set NSRDB_API_KEY or DEVELOPER_NLR_API_KEY in .env or environment."
        )
    if email is None:
        raise EnvironmentError(
            "No API email found. Set NSRDB_API_EMAIL or NREL_API_EMAIL in .env or environment."
        )
    return api_key, email


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------

def download_csv(url: str, output_path: Path, label: str, force: bool = False) -> bool:
    """Download url to output_path. Returns True on success."""
    if output_path.exists() and not force:
        print(f"  [skip] already exists: {output_path.name}")
        return True
    print(f"  Downloading {label} -> {output_path.name}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r:
            output_path.write_bytes(r.read())
        print(f"  Saved {output_path.name}")
        return True
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code} for {label}: {exc.read().decode(errors='ignore')[:200]}")
    except Exception as exc:
        print(f"  Error downloading {label}: {exc}")
    return False


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------

def solar_tmy_url(wkt: str, api_key: str, email: str) -> str:
    params = {
        "api_key":    api_key,
        "email":      email,
        "wkt":        wkt,
        "names":      SOLAR_TMY_NAME,
        "attributes": SOLAR_ATTRIBUTES,
        "interval":   60,
        "utc":        "false",
        "leap_day":   "false",
        "full_name":  "CO Zone TMY Solar",
        "affiliation":"Colorado Electric Model",
        "reason":     "LTA solar CF calibration",
    }
    return f"{SOLAR_TMY_URL}?{urllib.parse.urlencode(params, safe='(),')} "


def wind_year_url(wkt: str, year: int, api_key: str, email: str) -> str:
    params = {
        "api_key":    api_key,
        "email":      email,
        "wkt":        wkt,
        "names":      year,
        "attributes": WIND_ATTRIBUTES,
        "interval":   60,
        "utc":        "false",
        "leap_day":   "false",
        "full_name":  "CO Wind Point LTA",
        "affiliation":"Colorado Electric Model",
        "reason":     "LTA wind CF calibration",
    }
    return f"{WIND_URL}?{urllib.parse.urlencode(params, safe='(),')} "


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Download LTA solar/wind source data for calibration.")
    parser.add_argument(
        "--redownload", action="store_true",
        help="Force fresh downloads even for files that already exist locally.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    RAW_SOLAR_DIR.mkdir(parents=True, exist_ok=True)
    RAW_WIND_DIR.mkdir(parents=True, exist_ok=True)

    api_key, email = load_credentials()
    print(f"Credentials loaded.\n")

    # --- Solar TMY ---
    if not CENTROIDS_PATH.exists():
        raise FileNotFoundError(
            f"Zone centroids not found at {CENTROIDS_PATH}. Run script 10 first."
        )
    centroids = pd.read_csv(CENTROIDS_PATH)
    print(f"Downloading NSRDB TMY ({SOLAR_TMY_NAME}) for {len(centroids)} zones...")
    solar_ok = 0
    for _, row in centroids.iterrows():
        zone = row["zone"]
        wkt  = row["wkt"]
        out  = RAW_SOLAR_DIR / f"{zone}_tmy_solar.csv"
        url  = solar_tmy_url(wkt, api_key, email)
        if download_csv(url, out, f"TMY solar {zone}", force=args.redownload):
            solar_ok += 1
        time.sleep(1.1)
    print(f"Solar TMY: {solar_ok}/{len(centroids)} zones downloaded.\n")

    # --- Wind multi-year ---
    total_wind  = sum(len(pts) for pts in WIND_POINTS.values()) * len(WIND_YEARS)
    wind_ok = 0
    print(f"Downloading BC-HRRR wind for years {WIND_YEARS[0]}-{WIND_YEARS[-1]} "
          f"({len(WIND_YEARS)} years x 5 points = {total_wind} files)...")
    for zone, points in WIND_POINTS.items():
        for pt in points:
            wkt = f"POINT({pt['lon']} {pt['lat']})"
            for year in WIND_YEARS:
                out = RAW_WIND_DIR / f"{zone}_{year}_wind_point{pt['index']}.csv"
                url = wind_year_url(wkt, year, api_key, email)
                if download_csv(url, out, f"wind {zone} pt{pt['index']} {year}", force=args.redownload):
                    wind_ok += 1
                time.sleep(1.1)
    print(f"Wind: {wind_ok}/{total_wind} files downloaded.")


if __name__ == "__main__":
    main()
