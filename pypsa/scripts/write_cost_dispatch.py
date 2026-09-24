"""
Rebuild cost_by_year.csv, npv.csv, and dispatch_{year}.csv from checkpoints.

No solve. Run from the repo root:
  python -u pypsa/scripts/write_cost_dispatch.py core
"""

import os
import sys

import pypsa  # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_helpers import write_cost_dispatch_from_checkpoints


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "core"
    write_cost_dispatch_from_checkpoints(name)


if __name__ == "__main__":
    main()
