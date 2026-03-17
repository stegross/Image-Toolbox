"""Entry point for the VI-Toolbox application.

Run with::

    python -m app
"""

import sys

from app.core.application import Application


def main() -> None:
    """Launch the VI-Toolbox application."""
    sys.exit(Application().run())


if __name__ == "__main__":
    main()
