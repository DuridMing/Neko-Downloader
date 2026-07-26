"""Make `app` importable regardless of the directory pytest is invoked from.

Without this the suite only collects when cwd is backend/, which silently
turns "pytest" at the repo root (or in CI) into a wall of import errors.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
