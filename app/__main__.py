"""Entry point for the VI-Toolbox application.

Run with::

    python -m app
"""

import os
import sys
from pathlib import Path

# When running as a PyInstaller --onedir bundle, redirect PaddleX model lookups
# to the paddlex_data/ folder that was copied next to the executable at build time.
if getattr(sys, "frozen", False):
    os.environ.setdefault(
        "PADDLEX_HOME", str(Path(sys.executable).parent / "paddlex_data")
    )

from app.core.application import Application


def main() -> None:
    """Launch the VI-Toolbox application."""
    sys.exit(Application().run())


if __name__ == "__main__":
    main()
