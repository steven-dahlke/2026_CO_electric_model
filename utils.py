from pathlib import Path

def find_project_root(marker="requirements.txt"):
    """Finds the project root by searching for a marker file (e.g., requirements.txt) upward from this file's location."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    raise FileNotFoundError(f"Could not find {marker} in any parent directory.")
