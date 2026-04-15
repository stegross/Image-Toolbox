"""Identifier type configuration and OCR/detection framework registry."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger("vi_toolbox.tools.scibit.config")

# ---------------------------------------------------------------------------
# Identifier configuration
# ---------------------------------------------------------------------------


@dataclass
class IdentifierConfig:
    """Configuration for a single identifier pattern class.

    Parameters
    ----------
    name : str
        Human-readable name shown in the UI (e.g. "Standard C0xx-xx").
    regex : str
        Regular expression the OCR result must match to be auto-accepted.
        Use ``".*"`` to accept any text.
    polarity : str
        ``"auto"`` lets the pipeline decide; ``"dark_on_light"`` /
        ``"light_on_dark"`` forces a specific polarity.
    description : str
        Optional description shown in tooltips.
    """

    name: str
    regex: str
    polarity: str = "auto"
    description: str = ""


DEFAULT_IDENTIFIER_CONFIGS: list[IdentifierConfig] = [
    IdentifierConfig(
        name="Default (accept any)",
        regex=r".*",
        polarity="auto",
        description="Accept any OCR output without regex validation.",
    ),
    IdentifierConfig(
        name="Standard Cxxx-yy",
        regex=r"C\d{3}-\d{2}",
        polarity="auto",
        description="Matches identifiers like C074-26.",
    ),
    IdentifierConfig(
        name="Two-letter prefix + 1–4 digits",
        regex=r"[A-Z]{2}\d{1,4}",
        polarity="auto",
        description="Matches identifiers like XD1 or XD0001 (2 uppercase letters, 1–4 digits).",
    ),
]

# ---------------------------------------------------------------------------
# Framework registries
# ---------------------------------------------------------------------------

#: Names of supported text-detection frameworks.
DETECTION_FRAMEWORKS: list[str] = [
    "Tesseract",
    "PaddleOCR",
    "EasyOCR",
]

#: Names of supported OCR recognition frameworks.
OCR_FRAMEWORKS: list[str] = [
    "Tesseract",
    "PaddleOCR",
    "EasyOCR",
]

# ---------------------------------------------------------------------------
# Config file helpers
# ---------------------------------------------------------------------------


def load_identifier_configs(config_dir: Path) -> list[IdentifierConfig]:
    """Load identifier configs from *config_dir*/identifier_types.json.

    Falls back to :data:`DEFAULT_IDENTIFIER_CONFIGS` if the file is missing
    or cannot be parsed.

    Parameters
    ----------
    config_dir : Path
        Application config directory (provided by ConfigManager).

    Returns
    -------
    list[IdentifierConfig]
        Loaded (or default) identifier configurations.
    """
    path = config_dir / "identifier_types.json"
    if not path.exists():
        _save_default_configs(path)
        return list(DEFAULT_IDENTIFIER_CONFIGS)
    try:
        with path.open(encoding="utf-8") as fh:
            raw: list[dict] = json.load(fh)
        configs = [
            IdentifierConfig(
                name=entry["name"],
                regex=entry.get("regex", r".*"),
                polarity=entry.get("polarity", "auto"),
                description=entry.get("description", ""),
            )
            for entry in raw
            if "name" in entry
        ]
        return configs or list(DEFAULT_IDENTIFIER_CONFIGS)
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        _logger.warning("Failed to load identifier_types.json: %s", exc)
        return list(DEFAULT_IDENTIFIER_CONFIGS)


def _save_default_configs(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(
                [
                    {
                        "name": c.name,
                        "regex": c.regex,
                        "polarity": c.polarity,
                        "description": c.description,
                    }
                    for c in DEFAULT_IDENTIFIER_CONFIGS
                ],
                fh,
                indent=2,
            )
    except OSError as exc:
        _logger.warning("Could not write default identifier configs: %s", exc)
