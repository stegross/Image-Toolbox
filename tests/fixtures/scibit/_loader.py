"""Test-fixture loader for SCIBIT end-to-end tests.

Reconstructs the inputs that an interactive SCIBIT session would have
produced — a configured :class:`Pipeline` and a populated
:class:`CalibrationSession` — so tests can exercise the batch path
without driving the GUI calibration flow.

Two artefact categories:

* **Pipeline configuration** — a real production artefact, lives on disk
  under ``tests/fixtures/scibit/pipelines/`` and is loaded via the same
  code path the application uses.
* **Calibration recording** — a *test-only* concept. Calibration in
  production is freshly produced every run from interactive user input;
  for tests, the values an interactive session would have produced are
  recorded as a :class:`CalibrationRecording` in the test code itself
  (not on disk, because they are not configuration).

Layout under ``tests/fixtures/scibit/``::

    pipelines/<name>.json   — production-shape pipeline configuration
    batches/<name>/         — labelled image batch; filename stems are
                              the ground-truth identifiers
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

# Importing the pipelines package triggers subclass registration so
# Pipeline.for_id can resolve concrete classes by their PIPELINE_ID.
from app.tools.scibit import pipelines as _pipelines  # noqa: F401
from app.tools.scibit.config.config import Configuration
from app.tools.scibit.config.preset import IdentifierPatternPresetRegistry
from app.tools.scibit.core.pipeline import Pipeline, _preprocess_image
from app.tools.scibit.core.session import CalibrationSession
from app.tools.scibit.core.types import BoundingBox

PIPELINES_SUBDIR: Final = "pipelines"
BATCHES_SUBDIR: Final = "batches"

_SUPPORTED_IMAGE_SUFFIXES: Final = frozenset({".jpg", ".jpeg", ".png"})


def fixtures_root() -> Path:
    """Absolute path to ``tests/fixtures/scibit/``."""
    return Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Pipeline configuration (production-shape artefact)
# ---------------------------------------------------------------------------


def load_pipeline_from_fixture(name: str) -> Pipeline:
    """Build a configured pipeline from a fixture pipeline-configuration JSON.

    Mirrors the production loader path: :meth:`Configuration.load` parses
    the JSON, :meth:`Pipeline.for_id` resolves the concrete subclass, and
    :meth:`Pipeline.from_config` constructs the fully wired instance.

    Parameters
    ----------
    name : str
        Configuration filename stem (without ``.json``), relative to
        ``tests/fixtures/scibit/pipelines/``.

    Returns
    -------
    Pipeline
        Fully configured pipeline instance.

    Raises
    ------
    FileNotFoundError
        If no pipeline configuration with *name* exists.
    ValueError
        If the configuration references an unknown pipeline id.
    """
    path = fixtures_root() / PIPELINES_SUBDIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Pipeline fixture '{name}' not found at {path}.")
    config = Configuration.load(path)
    pipeline_cls = Pipeline.for_id(config.pipeline)
    if pipeline_cls is None:
        raise ValueError(
            f"Unknown pipeline id '{config.pipeline}' in fixture '{path}'. "
            "Ensure the matching pipeline module is imported."
        )
    presets = IdentifierPatternPresetRegistry()  # default-only is sufficient
    return pipeline_cls.from_config(config, presets)


# ---------------------------------------------------------------------------
# Calibration recording (test-only artefact, lives in code)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationRecording:
    """The two purely-interactive outputs of an interactive calibration.

    Every other quantity that calibration usually produces (rotation,
    colour inversion, downscale, ROI tolerance margin) is just the
    confirmed value of a stage parameter and therefore already lives in
    the pipeline configuration file. The two fields below are the only
    pieces a user actually *produces* with the mouse and folder picker
    during an interactive calibration:

    Parameters
    ----------
    calibration_image_filename : str
        Filename of the calibration image **within the batch directory**
        (e.g. ``"XA05.jpg"``), not a full path.
    identifier_roi : BoundingBox
        ``(x, y, width, height)`` of the identifier region as drawn
        during the recorded calibration.
    """

    calibration_image_filename: str
    identifier_roi: BoundingBox


def build_session_from_recording(
    batch_dir: Path,
    recording: CalibrationRecording,
    pipeline: Pipeline,
) -> CalibrationSession:
    """Reconstruct a :class:`CalibrationSession` from a code recording.

    Mirrors what
    :meth:`~app.tools.scibit.stages.calibration_setup_stage.CalibrationSetupStage.confirm_calibration`
    does in production: it reads the rotation, colour-inversion, and
    downscale values from the ``calibration_setup`` stage's parameters
    (loaded from the pipeline configuration), applies the same
    percent-to-fraction conversion to the downscale, runs the same
    preprocessing helper on the calibration image, and then layers the
    interactive outputs (the chosen ``identifier_roi`` and the
    ``roi_tolerance_margin`` parameter from
    ``identifier_region_selection``) onto the session.

    Parameters
    ----------
    batch_dir : Path
        Directory containing the batch images, including the calibration
        image referenced by ``recording.calibration_image_filename``.
    recording : CalibrationRecording
        The interactive calibration outputs (image choice + ROI).
    pipeline : Pipeline
        Pipeline whose stage parameters supply rotation, inversion,
        downscale, and tolerance margin.

    Returns
    -------
    CalibrationSession
        Populated session, ready for :meth:`Pipeline.run_batch`.

    Raises
    ------
    FileNotFoundError
        If the calibration image is missing from *batch_dir*.
    RuntimeError
        If the pipeline does not contain a ``calibration_setup`` stage.
    """
    setup = pipeline.get_stage("calibration_setup")
    if setup is None:
        raise RuntimeError(
            "Pipeline has no 'calibration_setup' stage — cannot resolve "
            "rotation / inversion / downscale defaults."
        )
    rotation = float(setup.parameters.get("rotation_degrees", 0.0))
    invert = bool(setup.parameters.get("invert_colors", False))
    downscale_pct = int(setup.parameters.get("downscale_factor", 100))
    downscale_factor = max(10, min(100, downscale_pct)) / 100.0

    selection = pipeline.get_stage("identifier_region_selection")
    if selection is not None:
        margin = int(selection.parameters.get("roi_tolerance_margin", 10))
    else:
        margin = 10  # CalibrationSession default

    image_path = batch_dir / recording.calibration_image_filename
    if not image_path.exists():
        raise FileNotFoundError(
            f"Calibration image '{image_path}' is missing — check "
            "CalibrationRecording.calibration_image_filename against the "
            "batch directory contents."
        )

    example_image = _preprocess_image(image_path, rotation, invert, downscale_factor)
    return CalibrationSession(
        example_image=example_image,
        rotation_degrees=rotation,
        invert_colors=invert,
        downscale_factor=downscale_factor,
        identifier_roi=recording.identifier_roi,
        roi_tolerance_margin=margin,
    )


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------


def batch_dir(batch_name: str) -> Path:
    """Absolute path to a fixture batch directory.

    The directory may not exist yet (e.g. on a fresh checkout); callers
    should check with :meth:`Path.is_dir` or use :func:`batch_images`,
    which already handles the missing-directory case.
    """
    return fixtures_root() / BATCHES_SUBDIR / batch_name


def batch_images(batch_name: str) -> list[Path]:
    """Return the image paths of a fixture batch, sorted lexicographically.

    Parameters
    ----------
    batch_name : str
        Subdirectory name under ``tests/fixtures/scibit/batches/``.

    Returns
    -------
    list[Path]
        Image paths. Empty list if the directory does not exist or
        contains no supported images.
    """
    directory = batch_dir(batch_name)
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _SUPPORTED_IMAGE_SUFFIXES
    )
