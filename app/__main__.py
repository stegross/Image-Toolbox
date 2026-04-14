"""Entry point for the VI-Toolbox application.

Run with::

    python -m app
"""

import os
import sys
from pathlib import Path

# When running as a PyInstaller --onedir bundle, set up paths that paddle and
# paddlex need to find their resources.
if getattr(sys, "frozen", False):
    _bundle_dir = Path(sys.executable).parent

    # Redirect PaddleX model lookups to the paddlex_data/ folder copied at build time.
    os.environ.setdefault("PADDLEX_HOME", str(_bundle_dir / "paddlex_data"))

    # paddle (paddlepaddle) ships native DLLs in paddle/libs/.  Register the
    # directory so Windows finds them when paddle loads its C extensions.
    _paddle_libs = _bundle_dir / "_internal" / "paddle" / "libs"
    if _paddle_libs.exists():
        os.add_dll_directory(str(_paddle_libs))

from app.core.application import Application


def main() -> None:
    """Launch the VI-Toolbox application."""
    sys.exit(Application().run())


if __name__ == "__main__":
    main()
