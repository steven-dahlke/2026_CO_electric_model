"""
Paper-case caller for the frozen Colorado PyPSA core.

Cases are named overlays on library defaults (the 8c stack).

Run unbuffered from the repo root:
  python -u pypsa/scripts/run_scenarios.py
  python -u pypsa/scripts/run_scenarios.py core
  python -u pypsa/scripts/run_scenarios.py no_co2_policy
  python -u pypsa/scripts/run_scenarios.py island
  python -u pypsa/scripts/run_scenarios.py island_no_co2_policy
  python -u pypsa/scripts/run_scenarios.py cap95
  python -u pypsa/scripts/run_scenarios.py island_cap95
  python -u pypsa/scripts/run_scenarios.py unconstrained_internal
  python -u pypsa/scripts/run_scenarios.py island_unconstrained_internal

Writes pypsa/scenarios/{name}/.
"""

import os
import sys

import pypsa  # noqa: F401

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_helpers import run_myopic_sequence

CASES: dict[str, dict] = {
    # Main text: core (Reference), island, no_co2_policy
    "core": {},
    "island": {"neighbors": False},
    "no_co2_policy": {"co2_cap": False},

    # Additional sensitivities discussed in Discussion/SI
    "island_no_co2_policy": {"neighbors": False, "co2_cap": False},
    "cap95": {"co2_path": "cap95"},
    "island_cap95": {"neighbors": False, "co2_path": "cap95"},
    "unconstrained_internal": {"internal_limits": False, "zonal_ra": False},
    "island_unconstrained_internal": {
        "internal_limits": False,
        "zonal_ra": False,
        "neighbors": False,
    },
}


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "core"
    if name not in CASES:
        known = ", ".join(sorted(CASES))
        raise SystemExit(f"Unknown case {name!r}. Known: {known}")
    run_myopic_sequence(
        network_prefix=name,
        title=f"Colorado PyPSA case: {name}",
        **CASES[name],
    )


if __name__ == "__main__":
    main()
