"""ResultsWidget — batch results display and manual review (spec Section 3.10).

Replaces the :class:`~app.tools.scibit.ui.CalibrationWidget` in the process
area after calibration completes.  Connects to pipeline signals, maps
:class:`~app.tools.scibit.core.types.ProcessingOutcome` →
:class:`~app.tools.scibit.core.types.ReviewState`, populates the results
list, auto-copies AUTO_ACCEPTED results, and manages the review queue.

Layout::

    ┌───────────────────────────────────────────────────────┐
    │  [=====Progress bar=====]                             │
    │  Total: X | Accepted: Y | Pending: Z | Manual: W | … │
    ├──────────────────────────┬────────────────────────────┤
    │                          │                            │
    │   QListWidget            │   ReviewPanel              │
    │   (results list)         │   (hidden until needed)   │
    │                          │                            │
    └──────────────────────────┴────────────────────────────┘
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.tools.scibit.core.types import (
    BatchResult,
    ProcessingOutcome,
    ReviewState,
    ReviewStateMapping,
)
from app.tools.scibit.ui._file_ops import copy_result_image
from app.tools.scibit.ui.review_panel import ReviewPanel

if TYPE_CHECKING:
    from app.tools.scibit.config.config import PipelineOptions
    from app.tools.scibit.core.pipeline import Pipeline
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal data class
# ---------------------------------------------------------------------------


@dataclass
class _ResultEntry:
    """Internal tracking object for one processed image."""

    result: BatchResult
    item: QListWidgetItem
    review_state: ReviewState
    image_path: Path


# ---------------------------------------------------------------------------
# ResultsWidget
# ---------------------------------------------------------------------------


class ResultsWidget(QWidget):
    """Batch results display, auto-copy, and manual review management.

    Parameters
    ----------
    pipeline : Pipeline
        The pipeline whose signals are connected.
    options : PipelineOptions
        Pipeline-level options; ``manual_confirmation_required`` selects
        the :class:`~ReviewStateMapping` mode.
    image_folder : Path | None
        Folder containing the batch images.  Required for file copy
        operations; if ``None``, file copies are skipped with a warning.
    session : CalibrationSession | None
        The calibration session whose Stage-0 transforms (rotation,
        inversion, downscale) are applied to the review preview so it
        matches what the pipeline processed.
    parent : QWidget | None
        Optional Qt parent.

    Signals
    -------
    batch_complete()
        Emitted when ``pipeline.batch_completed`` fires.  The SciBitTool
        connects to this to record timing and re-enable the control bar.
    """

    batch_complete = Signal()

    def __init__(
        self,
        pipeline: Pipeline,
        options: PipelineOptions,
        image_folder: Path | None = None,
        session: CalibrationSession | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._options = options
        self._image_folder = image_folder
        self._session = session
        self._mapping: dict[ProcessingOutcome, ReviewState] = ReviewStateMapping.select(
            options.manual_confirmation_required
        )

        self._entries: list[_ResultEntry] = []
        self._item_states: dict[int, ReviewState] = {}
        self._review_queue: list[_ResultEntry] = []
        self._review_idx: int = 0

        self._setup_ui()

        # Connect to pipeline signals. QueuedConnection is mandatory:
        # the pipeline runs on the batch worker thread (SciBitTool moves
        # it there before start()), and these slots touch widget state
        # that must only be mutated on the main thread.
        pipeline.image_completed.connect(
            self._on_image_completed,
            Qt.ConnectionType.QueuedConnection,
        )
        pipeline.progress_updated.connect(
            self._on_progress_updated,
            Qt.ConnectionType.QueuedConnection,
        )
        pipeline.batch_completed.connect(
            self._on_batch_completed,
            Qt.ConnectionType.QueuedConnection,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def has_unconfirmed(self) -> bool:
        """``True`` if any result still needs user action."""
        return any(
            state not in (ReviewState.AUTO_ACCEPTED, ReviewState.MANUALLY_CONFIRMED)
            for state in self._item_states.values()
        )

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Progress bar (hidden after batch completes)
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # Summary label
        self._summary_label = QLabel("Total: 0 | Accepted: 0 | Pending: 0 | Manual: 0 | Failed: 0")
        layout.addWidget(self._summary_label)

        # Horizontal splitter: results list (left) + review panel (right)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self._splitter, 1)

        self._results_list = QListWidget()
        self._results_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._splitter.addWidget(self._results_list)

        self._review_panel = ReviewPanel()
        self._review_panel.rename_applied.connect(self._on_rename_applied)
        self._review_panel.skipped.connect(self._on_skip)
        self._review_panel.navigate.connect(self._on_navigate)
        self._review_panel.setVisible(False)
        self._splitter.addWidget(self._review_panel)
        self._splitter.setSizes([500, 400])

    # ------------------------------------------------------------------
    # Pipeline signal handlers
    # ------------------------------------------------------------------

    def _on_image_completed(self, filename: str, result: BatchResult) -> None:
        """Append a list row for *result* whenever the pipeline finishes one image."""
        # Map outcome → review state.
        state = self._mapping.get(result.outcome, ReviewState.CRITICAL)

        # Create list item.
        item = QListWidgetItem(_format_item_text(result))
        r, g, b = state.color
        item.setBackground(QColor(r, g, b))
        self._results_list.addItem(item)

        # Determine full image path.
        img_path = self._image_folder / filename if self._image_folder else Path(filename)

        entry = _ResultEntry(
            result=result,
            item=item,
            review_state=state,
            image_path=img_path,
        )
        self._entries.append(entry)
        self._item_states[id(item)] = state

        # Auto-copy for AUTO_ACCEPTED in auto mode.
        if state == ReviewState.AUTO_ACCEPTED:
            self._auto_copy(entry)

        # Add to review queue if user action is needed.
        if state != ReviewState.AUTO_ACCEPTED:
            self._review_queue.append(entry)

        self._update_summary()

    def _on_progress_updated(self, current: int, total: int) -> None:
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)

    def _on_batch_completed(self, _results: list[BatchResult]) -> None:
        self._progress_bar.setVisible(False)
        self._update_summary()
        self.batch_complete.emit()

    # ------------------------------------------------------------------
    # User interaction handlers
    # ------------------------------------------------------------------

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Open the review panel for the double-clicked item."""
        state = self._item_states.get(id(item))
        if state in (ReviewState.AUTO_ACCEPTED, ReviewState.MANUALLY_CONFIRMED):
            return  # already handled — not reviewable

        entry = next((e for e in self._entries if e.item is item), None)
        if entry is None:
            return

        idx = next((i for i, e in enumerate(self._review_queue) if e is entry), None)
        if idx is None:
            return

        self._review_idx = idx
        self._load_review_panel()

    def _on_rename_applied(self, image_path: Path, new_identifier: str) -> None:
        """Handle ReviewPanel.rename_applied — copy file, mark confirmed."""
        if not self._review_queue:
            return

        entry = self._review_queue[self._review_idx]

        # Attempt file copy.
        new_filename = new_identifier  # fallback if copy fails
        if self._image_folder and new_identifier:
            try:
                dest = copy_result_image(entry.image_path, self._image_folder, new_identifier)
                new_filename = dest.name
            except Exception as exc:
                _log.warning("File copy failed for '%s': %s", entry.result.filename, exc)

        # Update list item.
        self._set_item_state(entry, ReviewState.MANUALLY_CONFIRMED)
        original = entry.result.filename
        entry.item.setText(f"{original} → {new_filename} | Manual | ✓")

        # Remove from review queue.
        self._review_queue.pop(self._review_idx)
        self._update_summary()
        self._advance_or_hide()

    def _on_skip(self, _image_path: Path) -> None:
        """Advance the queue pointer without confirming."""
        if not self._review_queue:
            return
        next_idx = self._review_idx + 1
        if next_idx >= len(self._review_queue):
            next_idx = min(self._review_idx, len(self._review_queue) - 1)
        self._review_idx = next_idx
        self._load_review_panel()

    def _on_navigate(self, delta: int) -> None:
        """Move the review queue pointer by *delta*."""
        if not self._review_queue:
            return
        self._review_idx = max(0, min(self._review_idx + delta, len(self._review_queue) - 1))
        self._load_review_panel()

    # ------------------------------------------------------------------
    # Review panel management
    # ------------------------------------------------------------------

    def _load_review_panel(self) -> None:
        if not self._review_queue:
            self._review_panel.setVisible(False)
            return

        self._review_idx = max(0, min(self._review_idx, len(self._review_queue) - 1))
        entry = self._review_queue[self._review_idx]
        session = self._session
        self._review_panel.load_result(
            image_path=entry.image_path,
            filename=entry.result.filename,
            ocr_text=entry.result.identifier_text,
            confidence=entry.result.confidence,
            has_prev=self._review_idx > 0,
            has_next=self._review_idx < len(self._review_queue) - 1,
            rotation_degrees=session.rotation_degrees if session else 0.0,
            invert_colors=session.invert_colors if session else False,
            downscale_factor=session.downscale_factor if session else 1.0,
        )
        self._review_panel.setVisible(True)

    def _advance_or_hide(self) -> None:
        if not self._review_queue:
            self._review_panel.setVisible(False)
            return
        self._review_idx = min(self._review_idx, len(self._review_queue) - 1)
        self._load_review_panel()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _auto_copy(self, entry: _ResultEntry) -> None:
        """Attempt an automatic file copy for AUTO_ACCEPTED results."""
        if not self._image_folder:
            _log.debug(
                "Auto-copy skipped for '%s': no image_folder set.",
                entry.result.filename,
            )
            return
        identifier = entry.result.identifier_text
        if not identifier:
            _log.debug(
                "Auto-copy skipped for '%s': empty identifier.",
                entry.result.filename,
            )
            return
        try:
            copy_result_image(entry.image_path, self._image_folder, identifier)
        except Exception as exc:
            _log.warning("Auto-copy failed for '%s': %s", entry.result.filename, exc)

    def _set_item_state(self, entry: _ResultEntry, state: ReviewState) -> None:
        entry.review_state = state
        self._item_states[id(entry.item)] = state
        r, g, b = state.color
        entry.item.setBackground(QColor(r, g, b))

    def _update_summary(self) -> None:
        states = list(self._item_states.values())
        total = len(states)
        accepted = sum(1 for s in states if s == ReviewState.AUTO_ACCEPTED)
        pending = sum(
            1 for s in states if s in (ReviewState.PENDING_REVIEW, ReviewState.NEEDS_ATTENTION)
        )
        manual = sum(1 for s in states if s == ReviewState.MANUALLY_CONFIRMED)
        failed = sum(1 for s in states if s == ReviewState.CRITICAL)
        self._summary_label.setText(
            f"Total: {total} | Accepted: {accepted} | "
            f"Pending: {pending} | Manual: {manual} | Failed: {failed}"
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _format_item_text(result: BatchResult) -> str:
    """Format the text shown in the results list for one *result*."""
    text = result.identifier_text or "(empty)"
    return f"{result.filename} | {text} | {result.confidence:.0f}%"
