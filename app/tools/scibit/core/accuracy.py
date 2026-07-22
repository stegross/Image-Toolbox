"""Filename-based accuracy reporting for SCIBIT batch results.

Used by the SCIBIT tool's "Test Mode" — where filenames encode the
ground-truth identifier — and by end-to-end integration tests that
exercise the full pipeline on a labelled reference batch.

A result is **correct** when ``identifier_text.strip()`` equals the
source filename's stem after stripping (case-sensitive). Empty
recognitions and processing errors count as wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.tools.scibit.core.types import BatchResult


@dataclass(frozen=True)
class FilenameAccuracyReport:
    """Aggregated filename-vs-recognition accuracy for one batch.

    Parameters
    ----------
    total : int
        Number of results evaluated.
    n_correct : int
        Number of results whose recognised text matched the filename stem.
    correct : list[str]
        Filenames of correctly recognised images.
    wrong : list[tuple[str, str, str]]
        ``(filename, expected, recognized)`` tuples for incorrect results.
    """

    total: int
    n_correct: int
    correct: list[str] = field(default_factory=list)
    wrong: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        """Accuracy in percent, ``0.0`` when *total* is zero."""
        return (self.n_correct / self.total * 100.0) if self.total else 0.0


def compute_filename_accuracy(results: list[BatchResult]) -> FilenameAccuracyReport:
    """Compare each result's recognised text against its filename stem.

    Parameters
    ----------
    results : list[BatchResult]
        Batch results as produced by
        :meth:`~app.tools.scibit.core.pipeline.Pipeline.run_batch`.

    Returns
    -------
    FilenameAccuracyReport
        Counts plus per-image breakdown of correct and wrong results.
    """
    correct: list[str] = []
    wrong: list[tuple[str, str, str]] = []
    for r in results:
        expected = Path(r.filename).stem.strip()
        recognized = r.identifier_text.strip()
        if recognized == expected:
            correct.append(r.filename)
        else:
            wrong.append((r.filename, expected, recognized))
    return FilenameAccuracyReport(
        total=len(results),
        n_correct=len(correct),
        correct=correct,
        wrong=wrong,
    )
