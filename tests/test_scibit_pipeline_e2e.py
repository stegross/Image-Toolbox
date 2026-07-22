"""End-to-end integration test for the SCIBIT pipeline.

Drives a configured Direct-ROI pipeline over a fixture batch whose image
filenames encode the ground-truth identifiers, and asserts that the
filename-based recognition accuracy stays above a regression threshold.

Two artefact categories support the test:

* a **pipeline configuration** under ``tests/fixtures/scibit/pipelines/``,
  loaded exactly as the application loads user-saved configurations;
* a **labelled image batch** under ``tests/fixtures/scibit/batches/``,
  with filename stems as ground truth.

Calibration values (ROI, rotation, inversion, downscale, tolerance
margin) are not configuration — they are outputs of an interactive
calibration session. They are recorded **in this file** as a
:class:`CalibrationRecording` instance, because they belong with the
test scenario, not with on-disk configuration.

When the batch directory or the calibration recording still carry
placeholder values, the test skips with a clear message rather than
failing, so the suite stays green on a fresh checkout.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from app.tools.scibit.core.accuracy import compute_filename_accuracy

from tests.fixtures.scibit._loader import (
    CalibrationRecording,
    batch_dir,
    batch_images,
    build_session_from_recording,
    load_pipeline_from_fixture,
)

_log = logging.getLogger(__name__)

# Deselected by the nox sessions (they run with -m "not e2e"), since the test
# depends on a labelled image batch and a working Tesseract install that are
# not available in a clean CI environment. Run it explicitly with:
#     pytest -m e2e
pytestmark = pytest.mark.e2e

_PIPELINE_FIXTURE = "easy_fas_batch_small_direct_roi"
_BATCH_NAME = "easy_fas_batch_small"
_ACCURACY_THRESHOLD_PERCENT = 80.0

# ---------------------------------------------------------------------------
# Calibration recording
# ---------------------------------------------------------------------------
#
# Only two values: the chosen calibration image and the drawn ROI rectangle.
# Everything else (rotation, inversion, downscale, ROI tolerance margin) is
# already in the pipeline configuration as stage parameters and is read
# from there by build_session_from_recording, mirroring production.
#
# To activate the test, replace the placeholders below with the values from
# your interactive calibration.
# ---------------------------------------------------------------------------

_EASY_FAS_BATCH_SMALL_DIRECT_ROI = CalibrationRecording(
    calibration_image_filename="XA05.jpg",  # file inside the batch directory
    identifier_roi=(1136, 2288, 88, 32),  # ← (x, y, w, h) from the calibration ROI rectangle
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reference_batch() -> list[Path]:
    """Return the image paths of the reference batch; skip if none exist."""
    images = batch_images(_BATCH_NAME)
    if not images:
        pytest.skip(
            f"Reference batch '{_BATCH_NAME}' is empty — populate "
            f"tests/fixtures/scibit/batches/{_BATCH_NAME}/ with labelled "
            "images (see its README.md)."
        )
    return images


@pytest.fixture(scope="module")
def direct_roi_pipeline(qapp):  # noqa: ANN001 — qapp fixture is pytest-qt-provided
    """Build the Direct-ROI pipeline from the fixture configuration.

    Requires the ``pytesseract`` binding and a working Tesseract install on
    PATH; skips the test otherwise.
    """
    pytest.importorskip("pytesseract")
    return load_pipeline_from_fixture(_PIPELINE_FIXTURE)


@pytest.fixture(scope="module")
def direct_roi_session(direct_roi_pipeline):  # noqa: ANN001
    """Build the calibration session from the in-code recording.

    The pipeline supplies the rotation / inversion / downscale / tolerance
    margin via its stage parameters (loaded from the pipeline config);
    only the calibration image and the ROI come from the recording.

    Skips the test if the recording still carries placeholder values or
    if the referenced calibration image is missing from the batch.
    """
    recording = _EASY_FAS_BATCH_SMALL_DIRECT_ROI
    roi = recording.identifier_roi
    if not recording.calibration_image_filename or roi[2] == 0 or roi[3] == 0:
        pytest.skip(
            "CalibrationRecording for the Direct-ROI scenario still carries "
            "placeholder values. Perform an interactive calibration in the "
            "SCIBIT GUI on the reference batch and fill in "
            "_EASY_FAS_BATCH_SMALL_DIRECT_ROI in this file."
        )
    try:
        return build_session_from_recording(batch_dir(_BATCH_NAME), recording, direct_roi_pipeline)
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDirectROIPipelineEndToEnd:
    """End-to-end regression: configured pipeline meets accuracy floor."""

    def test_meets_accuracy_threshold(
        self,
        direct_roi_pipeline,  # noqa: ANN001
        direct_roi_session,  # noqa: ANN001
        reference_batch: list[Path],
    ) -> None:
        """Run the configured pipeline over the batch; assert accuracy floor."""
        results = direct_roi_pipeline.run_batch(reference_batch, direct_roi_session)

        assert len(results) == len(reference_batch), (
            "Pipeline returned fewer results than batch images — likely a "
            "premature cancellation or stage exception."
        )

        report = compute_filename_accuracy(results)
        _log.info(
            "Accuracy on '%s': %d/%d (%.1f%%)",
            _BATCH_NAME,
            report.n_correct,
            report.total,
            report.accuracy,
        )
        _log.info("Correct (%d): %s", report.n_correct, report.correct)
        _log.info("Wrong (%d): %s", len(report.wrong), report.wrong)

        assert report.accuracy >= _ACCURACY_THRESHOLD_PERCENT, (
            f"Accuracy {report.accuracy:.1f}% below regression threshold "
            f"{_ACCURACY_THRESHOLD_PERCENT:.1f}%. "
            f"Wrong: {report.wrong}"
        )
