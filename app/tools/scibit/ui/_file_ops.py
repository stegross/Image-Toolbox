"""File-copy utilities for SCIBIT result output (spec Section 8.5).

Original image files are never modified.  On successful recognition a copy
is saved with the pattern ``{identifier}_{original_stem}.ext``.

JPEG → JPEG: bitwise copy via ``shutil.copy2`` (no re-encoding, quality
preserved).

Other formats → JPEG: read with OpenCV, write as JPEG quality 90.

Filename conflicts are resolved by inserting a numeric counter:
``{identifier}_{counter}_{original_stem}.ext``.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

_log = logging.getLogger(__name__)

_JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})


def copy_result_image(
    source: Path,
    dest_dir: Path,
    identifier: str,
) -> Path:
    """Copy *source* into *dest_dir* with an identifier-prefixed filename.

    Parameters
    ----------
    source : Path
        Original image file.
    dest_dir : Path
        Destination directory (typically the same folder as *source*).
    identifier : str
        Recognised identifier string used as the filename prefix.

    Returns
    -------
    Path
        Absolute path of the newly created copy.

    Raises
    ------
    OSError
        If the file cannot be read or written.
    ValueError
        If *identifier* is empty.
    """
    if not identifier:
        raise ValueError("copy_result_image: identifier must not be empty.")

    is_jpeg = source.suffix.lower() in _JPEG_SUFFIXES
    ext = source.suffix if is_jpeg else ".jpg"
    dest_path = _unique_path(dest_dir, identifier, source.stem, ext)

    if is_jpeg:
        shutil.copy2(str(source), str(dest_path))
    else:
        _transcode_to_jpeg(source, dest_path)

    _log.debug("Copied '%s' → '%s'.", source.name, dest_path.name)
    return dest_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _unique_path(
    dest_dir: Path,
    identifier: str,
    stem: str,
    ext: str,
) -> Path:
    """Return a path in *dest_dir* that does not yet exist.

    Tries ``{identifier}_{stem}{ext}`` first, then
    ``{identifier}_1_{stem}{ext}``, ``{identifier}_2_{stem}{ext}``, …
    """
    candidate = dest_dir / f"{identifier}_{stem}{ext}"
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = dest_dir / f"{identifier}_{counter}_{stem}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def _transcode_to_jpeg(source: Path, dest: Path) -> None:
    """Read *source* with OpenCV and write as JPEG quality 90 to *dest*."""
    import cv2  # type: ignore[import]

    image = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise OSError(f"OpenCV could not read image for transcoding: {source}")

    ok = cv2.imwrite(str(dest), image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise OSError(f"OpenCV could not write JPEG: {dest}")
