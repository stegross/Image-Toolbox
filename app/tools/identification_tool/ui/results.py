"""Results list widget with manual review panel."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.tools._shared.image_widgets import ImageArea
from app.tools.identification_tool.pipeline.base import (
    AbstractPipeline,
    CalibrationData,
    PipelineResult,
    ResultStatus,
    copy_as_identifier,
)

_logger = logging.getLogger("vi_toolbox.tools.scibit.results")

# ---------------------------------------------------------------------------
# Result list item colours
# ---------------------------------------------------------------------------

_COLOR_ACCEPTED = QColor(180, 230, 180)   # green  — auto-renamed
_COLOR_PENDING  = QColor(255, 235, 150)   # yellow — accepted, awaiting manual confirmation
_COLOR_FAILED   = QColor(240, 180, 180)   # red    — OCR failed, needs review
_COLOR_MANUAL   = QColor(160, 200, 240)   # blue   — manually confirmed and renamed


def _item_color(status: ResultStatus) -> QColor:
    return {
        ResultStatus.ACCEPTED: _COLOR_ACCEPTED,
        ResultStatus.PENDING:  _COLOR_PENDING,
        ResultStatus.FAILED:   _COLOR_FAILED,
        ResultStatus.MANUAL:   _COLOR_MANUAL,
    }[status]


# ---------------------------------------------------------------------------
# Review panel (shown when a failed entry is double-clicked)
# ---------------------------------------------------------------------------


class _ReviewPanel(QWidget):
    """Shows one image for manual identifier correction.

    Signals
    -------
    rename_applied
        ``(original_path, new_name)`` — user confirmed a rename.
    skipped
        ``(original_path)`` — user skipped this entry.
    navigate
        ``(delta: int)`` — +1 / -1 navigation request.
    """

    rename_applied = Signal(Path, str)
    skipped = Signal(Path)
    navigate = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Image area
        self._image_area = ImageArea(self)
        self._image_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._image_area, stretch=1)

        # Identifier region inset
        self._inset_label = QLabel()
        self._inset_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inset_label.setStyleSheet(
            "border: 1px solid gray; background: #1a1a1a; padding: 2px;"
        )
        self._inset_label.setFixedHeight(80)
        self._inset_label.hide()
        layout.addWidget(self._inset_label)

        # Entry info label
        self._info_label = QLabel()
        self._info_label.setStyleSheet("font-size: 11px; color: #555;")
        layout.addWidget(self._info_label)

        # Rename row
        rename_row = QHBoxLayout()
        rename_row.setSpacing(6)
        rename_row.addWidget(QLabel("Identifier:"))
        self._identifier_edit = QLineEdit()
        rename_row.addWidget(self._identifier_edit, stretch=1)
        layout.addLayout(rename_row)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._prev_btn = QPushButton("◀ Prev")
        self._prev_btn.setFixedWidth(80)
        self._prev_btn.clicked.connect(lambda: self.navigate.emit(-1))
        btn_row.addWidget(self._prev_btn)
        btn_row.addStretch()
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setFixedWidth(70)
        self._skip_btn.clicked.connect(self._on_skip)
        self._rename_btn = QPushButton("Rename")
        self._rename_btn.setFixedWidth(80)
        self._rename_btn.setDefault(True)
        self._rename_btn.clicked.connect(self._on_rename)
        btn_row.addWidget(self._skip_btn)
        btn_row.addWidget(self._rename_btn)
        self._next_btn = QPushButton("Next ▶")
        self._next_btn.setFixedWidth(80)
        self._next_btn.clicked.connect(lambda: self.navigate.emit(1))
        btn_row.addWidget(self._next_btn)
        layout.addLayout(btn_row)

        self._current_result: PipelineResult | None = None

        # Keyboard shortcuts for navigation
        sc_prev = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        sc_prev.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_prev.activated.connect(lambda: self.navigate.emit(-1))
        sc_next = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        sc_next.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_next.activated.connect(lambda: self.navigate.emit(1))

    def load_result(self, result: PipelineResult) -> None:
        """Display *result* for review."""
        self._current_result = result
        path = result.original_path
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self._image_area.set_pixmap(pixmap)
            self._image_area.set_filename_text(path.name)
        conf_text = f"{result.confidence:.0%}" if result.confidence >= 0 else "N/A"
        self._info_label.setText(
            f"{path.name}  |  OCR: {result.recognized_text or '—'}  |  Confidence: {conf_text}"
        )
        self._identifier_edit.setText(result.recognized_text or "")
        self._identifier_edit.setFocus()
        self._identifier_edit.selectAll()

    def set_navigation_state(self, has_prev: bool, has_next: bool) -> None:
        self._prev_btn.setEnabled(has_prev)
        self._next_btn.setEnabled(has_next)

    def _on_rename(self) -> None:
        if self._current_result is None:
            return
        new_name = self._identifier_edit.text().strip()
        if not new_name:
            return
        self.rename_applied.emit(self._current_result.original_path, new_name)

    def _on_skip(self) -> None:
        if self._current_result is not None:
            self.skipped.emit(self._current_result.original_path)


# ---------------------------------------------------------------------------
# ResultsWidget
# ---------------------------------------------------------------------------


class ResultsWidget(QWidget):
    """Shows the processing result list and drives the manual review panel.

    Parameters
    ----------
    images : list[Path]
        All images being processed (including already-renamed accepted ones).
    pipeline : AbstractPipeline
        The active pipeline; connects :attr:`~AbstractPipeline.image_processed`.
    min_confidence : float
        Threshold used to colour entries; not re-applied here.
    parent : QWidget | None
        Optional parent.

    Signals
    -------
    batch_complete
        Emitted when the pipeline reports batch completion.
    """

    batch_complete = Signal()

    def __init__(
        self,
        pipeline: AbstractPipeline,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        # {original_path_str -> (result, QListWidgetItem)}
        self._result_map: dict[str, tuple[PipelineResult, QListWidgetItem]] = {}
        self._review_paths: list[str] = []   # ordered list of FAILED + PENDING path strings
        self._review_index: int = -1

        self._setup_ui()
        self._connect_pipeline()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Progress bar (hidden after completion)
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        # Summary label
        self._summary_label = QLabel("Processing…")
        self._summary_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._summary_label)

        # Main splitter: list (left) + review panel (right)
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)

        self._list_widget = QListWidget()
        self._list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list_widget.setIconSize(QSize(48, 36))
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._splitter.addWidget(self._list_widget)

        self._review_panel = _ReviewPanel(self)
        self._review_panel.rename_applied.connect(self._on_rename_applied)
        self._review_panel.skipped.connect(self._on_skipped)
        self._review_panel.navigate.connect(self._on_navigate)
        self._review_panel.hide()
        self._splitter.addWidget(self._review_panel)

        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 2)
        layout.addWidget(self._splitter, stretch=1)

    def _connect_pipeline(self) -> None:
        self._pipeline.image_processed.connect(self._on_image_processed)
        self._pipeline.progress_updated.connect(self._on_progress_updated)
        self._pipeline.batch_complete.connect(self._on_batch_complete)

    # ------------------------------------------------------------------
    # Pipeline slots
    # ------------------------------------------------------------------

    def _on_image_processed(self, result: PipelineResult) -> None:
        path_str = str(result.original_path)
        item = self._make_list_item(result)
        self._list_widget.addItem(item)
        self._result_map[path_str] = (result, item)
        if result.status in (ResultStatus.FAILED, ResultStatus.PENDING):
            self._review_paths.append(path_str)
        self._update_summary()

    def _on_progress_updated(self, current: int, total: int) -> None:
        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(current)

    def _on_batch_complete(self) -> None:
        self._progress_bar.hide()
        self._update_summary()
        self.batch_complete.emit()

    # ------------------------------------------------------------------
    # List item helpers
    # ------------------------------------------------------------------

    def _make_list_item(self, result: PipelineResult) -> QListWidgetItem:
        name = result.original_path.name
        ocr = result.recognized_text or "—"
        conf = f"{result.confidence:.0%}" if result.confidence >= 0 else "?"
        text = f"{name}\n  OCR: {ocr}  |  {conf}"
        item = QListWidgetItem(text)
        item.setBackground(QBrush(_item_color(result.status)))
        item.setData(Qt.ItemDataRole.UserRole, str(result.original_path))
        item.setSizeHint(QSize(0, 52))
        return item

    def _update_item_color(self, path_str: str) -> None:
        if path_str in self._result_map:
            result, item = self._result_map[path_str]
            item.setBackground(QBrush(_item_color(result.status)))

    # ------------------------------------------------------------------
    # Double-click → open review panel
    # ------------------------------------------------------------------

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if path_str not in self._result_map:
            return
        result, _ = self._result_map[path_str]
        if result.status == ResultStatus.ACCEPTED:
            return  # no review needed for auto-renamed files
        if path_str in self._review_paths:
            self._review_index = self._review_paths.index(path_str)
        else:
            self._review_index = 0
        self._show_review_for_current()

    def _show_review_for_current(self) -> None:
        if not self._review_paths or self._review_index < 0:
            return
        path_str = self._review_paths[self._review_index]
        if path_str not in self._result_map:
            return
        result, _ = self._result_map[path_str]
        self._review_panel.show()
        self._review_panel.load_result(result)
        self._review_panel.set_navigation_state(
            has_prev=self._review_index > 0,
            has_next=self._review_index < len(self._review_paths) - 1,
        )
        for ps, (_, item) in self._result_map.items():
            item.setSelected(ps == path_str)

    # ------------------------------------------------------------------
    # Review panel slots
    # ------------------------------------------------------------------

    def _on_rename_applied(self, original_path: Path, new_name: str) -> None:
        path_str = str(original_path)
        new_path = copy_as_identifier(original_path, new_name)
        if new_path is None:
            return
        if path_str in self._result_map:
            old_result, item = self._result_map[path_str]
            new_result = PipelineResult(
                original_path=original_path,
                recognized_text=new_name,
                confidence=old_result.confidence,
                status=ResultStatus.MANUAL,
                new_path=new_path,
            )
            self._result_map[path_str] = (new_result, item)
            item.setText(f"{original_path.name} → {new_path.name}\n  Manual  |  ✓")
            item.setBackground(QBrush(_item_color(ResultStatus.MANUAL)))
        if path_str in self._review_paths:
            self._review_paths.remove(path_str)
            if self._review_index >= len(self._review_paths):
                self._review_index = max(0, len(self._review_paths) - 1)
        self._update_summary()
        if self._review_paths:
            self._show_review_for_current()
        else:
            self._review_panel.hide()

    def _on_skipped(self, original_path: Path) -> None:
        self._on_navigate(1)

    def _on_navigate(self, delta: int) -> None:
        if not self._review_paths:
            return
        self._review_index = max(0, min(len(self._review_paths) - 1, self._review_index + delta))
        self._show_review_for_current()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @property
    def has_unconfirmed(self) -> bool:
        """True if any result is still FAILED or PENDING (not yet confirmed)."""
        return any(
            r.status in (ResultStatus.FAILED, ResultStatus.PENDING)
            for r, _ in self._result_map.values()
        )

    def _update_summary(self) -> None:
        total = len(self._result_map)
        accepted = sum(1 for r, _ in self._result_map.values() if r.status == ResultStatus.ACCEPTED)
        pending  = sum(1 for r, _ in self._result_map.values() if r.status == ResultStatus.PENDING)
        manual   = sum(1 for r, _ in self._result_map.values() if r.status == ResultStatus.MANUAL)
        failed   = sum(1 for r, _ in self._result_map.values() if r.status == ResultStatus.FAILED)
        parts = [f"Total: {total}", f"Accepted: {accepted}"]
        if pending:
            parts.append(f"Pending: {pending}")
        parts += [f"Manual: {manual}", f"Failed: {failed}"]
        self._summary_label.setText("  |  ".join(parts))


# ---------------------------------------------------------------------------
# Rename helper
# ---------------------------------------------------------------------------


