import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from utils import find_project_root

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = find_project_root()
DATA_LOAD = PROJECT_ROOT / "data_cleaning" / "load"
output_path = DATA_LOAD / "load_shapes_zone_sector_2018.csv"
efs_path = DATA_LOAD / "EFSLoadProfile_Reference_Moderate.csv"

# ---------------------------------------------------------------------------
# Load EFS CSV and extract CO Industrial 2018 Reference/Moderate hourly series
# ---------------------------------------------------------------------------
# Columns: Electrification, TechnologyAdvancement, Year, LocalHourID,
#          State, Sector, Subsector, LoadMW
# There are 3 subsectors (machine drives, other, process heat) — sum them all.
print(f"Reading {efs_path.name}...")
df = pd.read_csv(efs_path)
print(f"  Shape: {df.shape}")

mask = (
    (df["Electrification"] == "Reference") &
    (df["TechnologyAdvancement"] == "Moderate") &
    (df["Year"] == 2018) &
    (df["State"] == "CO") &
    (df["Sector"] == "Industrial")
)
co_ind = df.loc[mask].groupby("LocalHourID")["LoadMW"].sum().sort_index()

assert len(co_ind) == 8760, (
    f"Expected 8760 hourly values for CO Industrial 2018, got {len(co_ind)}"
)
print(f"  Extracted {len(co_ind)} hourly values for CO Industrial 2018 (Reference/Moderate)")
ind_series = co_ind.values

# ---------------------------------------------------------------------------
# Timezone shift: EST -> MST (-2 hours), consistent with res/com shapes
# Normalize to unit shape
# ---------------------------------------------------------------------------
ind_series = np.roll(ind_series, -2)
ind_shape = ind_series / ind_series.sum()
print(f"  Industrial shape sum: {ind_shape.sum():.6f}")

# ---------------------------------------------------------------------------
# Append Industrial column to existing zone-sector CSV and re-save
# ---------------------------------------------------------------------------
output_df = pd.read_csv(output_path, index_col="hour")
output_df["Industrial"] = ind_shape

output_df.to_csv(output_path)
print(f"\nUpdated {output_path}")
print(f"Shape: {output_df.shape}  (rows=hours, cols=zone-sector+industrial)")
print(f"\nAll column sums (should all be 1.0):")
print(output_df.sum().to_string())
