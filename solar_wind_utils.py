"""
Shared simulation functions and ATB 2024 parameter constants for solar and wind
capacity factor calculations. Imported by scripts 12, 13, and 15.
Script 11 is a download-only script and does not use these simulation functions.

Centralizing these here ensures that parameter changes (e.g., ATB sensitivity
runs) propagate consistently across the generation profile and calibration scripts.
"""

from pathlib import Path

import pandas as pd
import PySAM.Pvwattsv8 as pv
import PySAM.Windpower as wp

# ---------------------------------------------------------------------------
# Solar — PVWatts V8 parameters (NREL ATB 2024, utility-scale PV)
# Revise here for sensitivity analysis; do not scatter magic numbers.
# ---------------------------------------------------------------------------
PARAMS = dict(
    system_capacity=1.0,   # kW-DC; scaling-invariant, AC output (W) = CF numerically
    module_type=1,         # Premium monocrystalline Si (PERC/TOPCon), dominant since 2022
    array_type=2,          # 1-axis horizontal tracking
    dc_ac_ratio=1.34,      # inverter loading ratio; NREL ATB 2024 utility-scale PV baseline
    losses=14.08,          # % total system losses: soiling, wiring, shading, availability
    inv_eff=96.0,          # % inverter efficiency
    tilt=0.0,              # degrees; horizontal tracker rotation axis
    azimuth=180.0,         # degrees; south-facing tracker axis
)

# ---------------------------------------------------------------------------
# Wind — ATB 2024 T1 turbine specs (power curve inputs) and simulation params
# Revise here for sensitivity analysis; do not scatter magic numbers.
# ---------------------------------------------------------------------------
ATB_T1 = dict(
    turbine_size    = 6000.0,   # kW;  NREL ATB 2024 T1 rated capacity
    rotor_diameter  = 170,      # m;   NREL ATB 2024 T1
    elevation       = 0.0,      # m;   air density correction handled via weather data
    max_cp          = 0.46,     # max power coefficient; typical modern 3-stage geared
    max_tip_speed   = 85.0,     # m/s; typical land-based turbine with 170 m rotor
    max_tip_sp_ratio= 9.0,      # tip speed ratio; typical modern turbine
    cut_in          = 3.0,      # m/s; industry standard cut-in speed
    cut_out         = 25.0,     # m/s; industry standard cut-out speed
    drive_train     = 0,        # 0 = 3-stage planetary; most common geared onshore
)

FARM = dict(
    hub_ht          = 115.0,    # m;   NREL ATB 2024 T1 hub height
    rotor_diameter  = 170.0,    # m;   NREL ATB 2024 T1
    system_capacity = 6000.0,   # kW;  one turbine, CF = gen_kWh / 6000
    shear           = 0.14,     # Hellmann exponent; flat terrain (CO eastern plains)
    wake_model      = 0,        # no wake losses; single representative turbine
    turbulence_coeff= 0.1,      # 10% turbulence intensity; typical flat terrain
)


# ---------------------------------------------------------------------------
# Solar functions
# ---------------------------------------------------------------------------

def parse_nsrdb(path: Path) -> tuple[dict, pd.DataFrame]:
    """Return (solar_resource_data dict for PySAM, data DataFrame) from NSRDB CSV.

    Handles both AMY files (e.g., Denver_2018_solar.csv) and TMY files
    (e.g., Denver_tmy_solar.csv) — the NSRDB CSV layout is identical for both.

    NSRDB CSV layout:
      Row 1: metadata (Latitude, Longitude, Time Zone, Elevation, ...)
      Row 2: unit labels
      Row 3: column headers (Year, Month, Day, Hour, Minute, GHI, DNI, DHI, ...)
      Row 4+: hourly data, timestamps at :30 (midpoint-of-hour NSRDB convention)
    """
    meta = pd.read_csv(path, nrows=1)
    df   = pd.read_csv(path, skiprows=2)

    resource = {
        "lat":    float(meta["Latitude"][0]),
        "lon":    float(meta["Longitude"][0]),
        "tz":     float(meta["Time Zone"][0]),
        "elev":   float(meta["Elevation"][0]),
        "year":   tuple(df["Year"]),
        "month":  tuple(df["Month"]),
        "day":    tuple(df["Day"]),
        "hour":   tuple(df["Hour"]),
        "minute": tuple(df["Minute"]),
        "dn":     tuple(df["DNI"]),
        "df":     tuple(df["DHI"]),
        "gh":     tuple(df["GHI"]),
        "wspd":   tuple(df["Wind Speed"]),
        "tdry":   tuple(df["Temperature"]),
    }
    return resource, df


def run_pvwatts(resource_data: dict, params: dict = PARAMS) -> list[float]:
    """Run PVWatts V8 and return hourly AC capacity factors (kW-AC per kW-DC)."""
    model = pv.new()
    model.SolarResource.solar_resource_data = resource_data
    for k, v in params.items():
        setattr(model.SystemDesign, k, v)
    model.execute()
    return [w / 1000.0 for w in model.Outputs.ac]


# ---------------------------------------------------------------------------
# Wind functions
# ---------------------------------------------------------------------------

def build_power_curve(p: dict = ATB_T1) -> tuple[tuple, tuple]:
    """Generate ATB 2024 T1 power curve via SAM's built-in physics model.

    Called once at startup; results reused for all wind site runs.
    calculate_powercurve raises a spurious SystemError from its C extension
    even on success — the curve is populated correctly so we suppress it.
    """
    m = wp.new()
    m.Resource.wind_resource_model_choice = 0
    try:
        m.Turbine.calculate_powercurve(
            p["turbine_size"], p["rotor_diameter"], p["elevation"],
            p["max_cp"], p["max_tip_speed"], p["max_tip_sp_ratio"],
            p["cut_in"], p["cut_out"], p["drive_train"],
        )
    except SystemError:
        pass  # spurious C-extension error; curve is populated correctly
    speeds = tuple(m.Turbine.wind_turbine_powercurve_windspeeds)
    power  = tuple(m.Turbine.wind_turbine_powercurve_powerout)
    if not speeds or max(power) == 0:
        raise RuntimeError("calculate_powercurve produced an empty or zero power curve")
    return speeds, power


def parse_bchrrr(path: Path) -> tuple[dict, pd.DataFrame]:
    """Return (wind_resource_data dict for PySAM, data DataFrame) from BC-HRRR CSV.

    BC-HRRR CSV layout:
      Row 1: interleaved key-value metadata —
             SiteID,<id>,Site Timezone,<tz>,Data Timezone,<tz>,Longitude,<lon>,Latitude,<lat>
      Row 2: column headers — Year,Month,Day,Hour,Minute,
             Wind Speed at 100m (m/s),Wind Direction at 100m (deg),
             Air Temperature at 100m (C),Surface Air Pressure (Pa)
      Row 3+: hourly data, timestamps at :00 (top of hour), UTC-7 fixed

    Columns referenced by position to avoid degree-symbol encoding issues on Windows.
    Pressure converted from Pa to atm (SAM expects atm).
    """
    meta_raw = pd.read_csv(path, nrows=1, header=None).iloc[0].tolist()
    meta = {str(meta_raw[i]): meta_raw[i + 1] for i in range(0, len(meta_raw) - 1, 2)}  # noqa: F841

    df = pd.read_csv(path, skiprows=1)

    resource = {
        "heights": [100.0, 100.0, 100.0, 100.0],
        "fields":  [3, 4, 1, 2],   # speed, direction, temperature, pressure
        "data":    list(zip(
            df.iloc[:, 5],            # wind speed (m/s)
            df.iloc[:, 6],            # wind direction (deg)
            df.iloc[:, 7],            # air temperature (C)
            df.iloc[:, 8] / 101325.0, # surface pressure Pa -> atm
        )),
    }
    return resource, df


def run_windpower(resource_data: dict, curve_speeds: tuple, curve_power: tuple,
                  farm: dict = FARM) -> list[float]:
    """Run SAM Windpower and return hourly AC capacity factors (kWh per kW rated)."""
    model = wp.new()
    model.Resource.wind_resource_data         = resource_data
    model.Resource.wind_resource_model_choice = 0
    model.Turbine.wind_turbine_hub_ht         = farm["hub_ht"]
    model.Turbine.wind_turbine_rotor_diameter = farm["rotor_diameter"]
    model.Turbine.wind_turbine_powercurve_windspeeds = curve_speeds
    model.Turbine.wind_turbine_powercurve_powerout   = curve_power
    model.Turbine.wind_resource_shear         = farm["shear"]
    model.Farm.system_capacity                = farm["system_capacity"]
    model.Farm.wind_farm_xCoordinates         = [0.0]
    model.Farm.wind_farm_yCoordinates         = [0.0]
    model.Farm.wind_farm_wake_model           = farm["wake_model"]
    model.Farm.wind_resource_turbulence_coeff = farm["turbulence_coeff"]
    model.execute()
    rated_kw = farm["system_capacity"]
    return [g / rated_kw for g in model.Outputs.gen]


# ---------------------------------------------------------------------------
# Shared utility
# ---------------------------------------------------------------------------

def build_datetime_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Build a DatetimeIndex from Year/Month/Day/Hour/Minute columns."""
    return pd.to_datetime(
        df[["Year", "Month", "Day", "Hour", "Minute"]].rename(
            columns={"Year": "year", "Month": "month", "Day": "day",
                     "Hour": "hour", "Minute": "minute"}
        )
    )
