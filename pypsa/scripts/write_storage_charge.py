"""
Write storage_charge_by_year.csv from checkpoints.

No solve. Backfill for scenarios solved before storage_charge_by_carrier()
was added to model_helpers.py. Run from the repo root:
  python -u pypsa/scripts/write_storage_charge.py core
"""

import os
import sys

import pypsa  # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_helpers import write_storage_charge_from_checkpoints


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "core"
    write_storage_charge_from_checkpoints(name)


if __name__ == "__main__":
    main()
