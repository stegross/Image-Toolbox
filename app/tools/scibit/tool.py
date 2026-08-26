"""SciBitTool — main tool class integrating with the VI-Toolbox host shell.

Implements :class:`~app.plugin.base.IToolPlugin` and orchestrates the full
SCIBIT workflow: folder selection → calibration → batch processing → review.

Spec references: Sections 3.7 (session persistence), 3.10 (UI architecture),
8.6 (timing), 9 (host shell integration).
"""

from __future__ import annotations

import logging
import time
from abc import ABCMeta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from PySide6.QtCore import QFile, Qt, QThread
from PySide6.QtGui import QCloseEvent
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config import ConfigManager
from app.plugin.base import IToolPlugin
from app.plugin.categories import ToolCategory
from app.tools.scibit.config import (
    Configuration,
    DebugExportMode,
    IdentifierPatternPresetRegistry,
    PipelineConfigStore,
    PipelineOptions,
    SessionConfig,
    StageConfig,
)
from app.tools.scibit.core.accuracy import compute_filename_accuracy
from app.tools.scibit.core.types import BatchResult
from app.tools.scibit.ui import CalibrationWidget, ResultsWidget

if TYPE_CHECKING:
    from app.tools.scibit.core.pipeline import Pipeline
    from app.tools.scibit.core.session import CalibrationSession

_log = logging.getLogger("vi_toolbox.tools.scibit")

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})

_NO_IDENTIFICATION_CONFIG = "— None —"

# Prefixes used in the identification-config combo box display text.
_BUNDLED_PREFIX = "(bundled)"
_CHANGED_PREFIX = "(changed)"


def _config_display_text(name: str, is_bundled: bool, is_dirty: bool = False) -> str:
    """Build the combo-box display text for a config entry.

    The ``(changed)`` prefix is always first (it refers to the live form
    state), followed by ``(bundled)`` (refers to the config source),
    then the canonical name.
    """
    parts: list[str] = []
    if is_dirty:
        parts.append(_CHANGED_PREFIX)
    if is_bundled:
        parts.append(_BUNDLED_PREFIX)
    parts.append(name)
    return " ".join(parts)


_DEBUG_MODE_VALUES = [
    DebugExportMode.DISABLED,
    DebugExportMode.CALIBRATION,
    DebugExportMode.ALL,
]


# ---------------------------------------------------------------------------
# QThread wrapper for blocking run_batch
# ---------------------------------------------------------------------------


class _BatchThread(QThread):
    """Runs Pipeline.run_batch on a background thread.

    The pipeline is moved onto this thread before ``start()`` so its Qt
    signals carry the worker's thread affinity — auto-connected slots on
    main-thread receivers are then correctly delivered via QueuedConnection.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        images: list[Path],
        session: CalibrationSession,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        self._images = images
        self._session = session

    def run(self) -> None:
        try:
            self._pipeline.run_batch(self._images, self._session)
        except Exception as exc:
            _log.error("Batch thread raised an unhandled exception: %s", exc, exc_info=True)

    def cancel(self) -> None:
        """Ask the pipeline to stop after the current image finishes.

        Safe to call from the main thread — flag writes are GIL-atomic
        and the pipeline's ``run_batch`` loop polls the flag between
        images.  Caller should follow this with ``wait()`` to join.
        """
        self._pipeline.cancel()


# ---------------------------------------------------------------------------
# Metaclass shim (QWidget + ABCMeta conflict)
# ---------------------------------------------------------------------------


class _ToolMeta(type(QWidget), ABCMeta):
    pass


# ---------------------------------------------------------------------------
# SciBitTool
# ---------------------------------------------------------------------------


class Scibit(QWidget, IToolPlugin, metaclass=_ToolMeta):
    """SCIBIT main tool widget — host shell plugin entry point.

    Parameters
    ----------
    config_manager : ConfigManager
        Application-wide config manager for session persistence.
    deployment_root : Path
        Root directory for embedded configs (packaged_configs folder).
    user_config_dir : Path
        User profile config directory.
    parent : QWidget | None
        Optional Qt parent.
    """

    # IToolPlugin class attributes
    name: ClassVar[str] = "SCIBIT"
    category: ClassVar[ToolCategory] = ToolCategory.IDENTIFICATION
    description: ClassVar[str] = "Single Chip Image Batch Identification Tool"
    icon_path: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    logger_name: ClassVar[str] = "vi_toolbox.tools.scibit"
    allow_multiple_instances: ClassVar[bool] = False
    closable: ClassVar[bool] = True
    handles_folders: ClassVar[bool] = True
    handled_path_extensions: ClassVar[frozenset[str]] = frozenset()

    def __init__(
        self,
        config_manager: ConfigManager,
        user_config_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        QWidget.__init__(self, parent)

        self._config_manager = config_manager
        self._user_config_dir = user_config_dir
        self._config_store = PipelineConfigStore.from_config_roots(
            user_config_dir=user_config_dir,
        )
        self._preset_registry = self._load_preset_registry()

        self._folder: Path | None = None
        self._images: list[Path] = []
        self._running = False

        self._current_pipeline: Pipeline | None = None
        self._calib_session: CalibrationSession | None = None
        self._configuration: Configuration | None = None
        self._batch_thread: _BatchThread | None = None

        self._calib_widget: CalibrationWidget | None = None
        self._results_widget: ResultsWidget | None = None

        # Currently-loaded identification config — used to carry stage configs
        # forward when saving before a pipeline exists, and to detect drift
        # during calibration via the "(changed)" indicator.
        self._loaded_config: Configuration | None = None
        self._loaded_config_name: str | None = None
        self._loaded_config_bundled: bool = False
        self._loaded_config_snapshot: dict | None = None
        self._dirty: bool = False
        # Set while applying a loaded config to widgets so the cascading
        # widget signals don't briefly flag the form as dirty.
        self._suspend_dirty_check: bool = False

        self._t_run_start: float | None = None
        self._t_calib_done: float | None = None
        self._t_batch_done: float | None = None

        # Captured from pipeline.batch_completed; consumed by the test-mode
        # accuracy summary in _on_batch_complete.
        self._batch_results: list[BatchResult] = []

        self._setup_ui()
        self._populate_combos()
        self._restore_session()

    # ------------------------------------------------------------------
    # IToolPlugin interface
    # ------------------------------------------------------------------

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return the widget the host shell embeds for this tool instance."""
        self.setParent(parent)
        return self

    def _assign_instance_id(self, instance_id: int) -> None:
        super()._assign_instance_id(instance_id)

    def accepts_path(self, path: Path) -> bool:
        """Return ``True`` if *path* is a directory — SCIBIT operates on image folders."""
        return path.is_dir()

    def open_from_path(self, path: Path) -> None:
        """Load *path* as the active image folder, prompting on unconfirmed results."""
        if not path.is_dir():
            return
        if self._has_unconfirmed():
            reply = QMessageBox.question(
                self,
                "Open New Folder",
                "Not all results have been confirmed yet.\n"
                "Open a new folder and lose unconfirmed results?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._set_folder(path)

    def can_close(self) -> bool:
        """Return ``True`` if no unconfirmed results remain, else prompt the user."""
        if not self._has_unconfirmed():
            return True
        reply = QMessageBox.question(
            self,
            "Unconfirmed Results",
            "Not all results have been confirmed yet.\nClose anyway and lose unconfirmed results?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Yes

    def on_close(self) -> None:
        """Persist the session and tear down the active pipeline and batch thread."""
        self._save_session()
        if self._batch_thread and self._batch_thread.isRunning():
            self._batch_thread.quit()
            self._batch_thread.wait(2000)
        if self._current_pipeline is not None:
            self._current_pipeline.cleanup()
            self._current_pipeline = None

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        ui_path = Path(__file__).parent / "tool.ui"
        loader = QUiLoader()
        qfile = QFile(str(ui_path))
        if not qfile.open(QFile.OpenModeFlag.ReadOnly):
            _log.error("Cannot open tool.ui: %s", ui_path)
            outer.addWidget(QLabel("Error: tool.ui not found.", self))
            return

        self._form = loader.load(qfile, self)
        qfile.close()

        if self._form is None:
            _log.error("QUiLoader failed to load tool.ui")
            outer.addWidget(QLabel("Error loading UI.", self))
            return

        outer.addWidget(self._form)

        # Retrieve widget references by object name.
        self._select_folder_btn: QPushButton = self._form.findChild(
            QPushButton, "select_folder_btn"
        )
        self._folder_path_edit: QLineEdit = self._form.findChild(QLineEdit, "folder_path_edit")
        self._start_btn: QPushButton = self._form.findChild(QPushButton, "start_btn")
        self._identification_config_combo: QComboBox = self._form.findChild(
            QComboBox, "identification_config_combo"
        )
        self._save_config_btn: QPushButton = self._form.findChild(QPushButton, "save_config_btn")
        self._config_group = self._form.findChild(QWidget, "config_group")
        self._pipeline_combo: QComboBox = self._form.findChild(QComboBox, "pipeline_combo")
        self._preset_combo: QComboBox = self._form.findChild(QComboBox, "preset_combo")
        self._manual_confirmation_check: QCheckBox = self._form.findChild(
            QCheckBox, "manual_confirmation_check"
        )
        self._confidence_spin: QDoubleSpinBox = self._form.findChild(
            QDoubleSpinBox, "confidence_spin"
        )
        self._debug_mode_combo: QComboBox = self._form.findChild(QComboBox, "debug_mode_combo")
        self._test_mode_check: QCheckBox = self._form.findChild(QCheckBox, "test_mode_check")
        self._process_area_frame: QFrame = self._form.findChild(QFrame, "process_area_frame")

        # Connect signals.
        self._select_folder_btn.clicked.connect(self._on_select_folder)
        self._start_btn.clicked.connect(self._on_start_stop)
        if self._identification_config_combo:
            self._identification_config_combo.currentIndexChanged.connect(
                self._on_identification_config_changed
            )
        if self._save_config_btn:
            self._save_config_btn.clicked.connect(self._on_save_config_btn)
        if self._config_group:
            self._config_group.toggled.connect(self._on_config_toggled)
            self._on_config_toggled(self._config_group.isChecked())

        # Pipeline-option widgets and the pipeline selector all contribute
        # to the saved Configuration, so any change has to refresh the
        # "(changed)" indicator the same way stage parameters do.
        if self._pipeline_combo:
            self._pipeline_combo.currentIndexChanged.connect(lambda *_: self._refresh_dirty_state())
        if self._preset_combo:
            self._preset_combo.currentIndexChanged.connect(lambda *_: self._refresh_dirty_state())
        if self._manual_confirmation_check:
            self._manual_confirmation_check.toggled.connect(lambda *_: self._refresh_dirty_state())
        if self._confidence_spin:
            self._confidence_spin.valueChanged.connect(lambda *_: self._refresh_dirty_state())
        if self._debug_mode_combo:
            self._debug_mode_combo.currentIndexChanged.connect(
                lambda *_: self._refresh_dirty_state()
            )

        # Style placeholder label.
        placeholder = self._process_area_frame.findChild(QLabel, "process_placeholder_label")
        if placeholder:
            placeholder.setStyleSheet("color: gray; font-size: 14px;")

    # ------------------------------------------------------------------
    # Combo population
    # ------------------------------------------------------------------

    def _populate_combos(self) -> None:
        # Identification config combo: sentinel + saved configs.  Each saved
        # entry stores a ``(name, is_bundled)`` tuple in UserRole data so the
        # displayed text can carry "(bundled)" / "(changed)" prefixes without
        # polluting save paths, and the loader knows which source to read.
        if self._identification_config_combo:
            self._identification_config_combo.blockSignals(True)
            self._identification_config_combo.clear()
            self._identification_config_combo.addItem(_NO_IDENTIFICATION_CONFIG)
            self._identification_config_combo.setItemData(0, None, Qt.ItemDataRole.UserRole)
            for name, is_bundled in self._config_store.list_config_entries():
                display_name = _config_display_text(name, is_bundled)
                tooltip = (
                    "Bundled configuration (read-only, cannot be edited)"
                    if is_bundled
                    else "User configuration"
                )
                self._identification_config_combo.addItem(display_name)
                idx = self._identification_config_combo.count() - 1
                self._identification_config_combo.setItemData(
                    idx, (name, is_bundled), Qt.ItemDataRole.UserRole
                )
                self._identification_config_combo.setItemData(
                    idx, tooltip, Qt.ItemDataRole.ToolTipRole
                )
            self._identification_config_combo.blockSignals(False)

        # Pipeline combo: discovered from Pipeline.__subclasses__(). The
        # pipelines package import above ensures every concrete subclass
        # is registered. Each item stores its class as userData so we
        # can instantiate without a separate id→class lookup.
        if self._pipeline_combo:
            import app.tools.scibit.pipelines  # noqa: F401  (subclass registration)
            from app.tools.scibit.core.pipeline import Pipeline

            self._pipeline_combo.blockSignals(True)
            self._pipeline_combo.clear()
            for cls in Pipeline.__subclasses__():
                self._pipeline_combo.addItem(cls.PIPELINE_ID, userData=cls)
            self._pipeline_combo.blockSignals(False)

        # Preset combo: all presets from registry.
        if self._preset_combo:
            self._preset_combo.clear()
            for name in self._preset_registry.get_preset_names():
                preset = self._preset_registry.get_preset(name)
                self._preset_combo.addItem(name)
                idx = self._preset_combo.count() - 1
                if preset.description:
                    self._preset_combo.setItemData(
                        idx, preset.description, Qt.ItemDataRole.ToolTipRole
                    )

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _load_preset_registry(self) -> IdentifierPatternPresetRegistry:
        """Load presets from embedded resource.

        Returns
        -------
            Registry with presets from the bundled scibit_regex_presets
            data (embedded in the EXE in a frozen build, or read from
            the dev JSON file when running from source).
        """
        from app.core.resources import load_bundled_presets_data

        presets_data = load_bundled_presets_data()
        return IdentifierPatternPresetRegistry.from_data(presets_data)

    def _restore_session(self) -> None:
        session = SessionConfig.load(self._config_manager)
        if session.last_folder:
            self._set_folder(session.last_folder, save=False)
        if self._test_mode_check is not None:
            self._test_mode_check.setChecked(session.test_mode)
            self._test_mode_check.toggled.connect(lambda _checked: self._save_session())

        last_name = session.last_pipeline_config_name
        last_bundled = session.last_pipeline_config_bundled
        if (
            last_name
            and self._identification_config_combo
            and self._config_store.config_exists(last_name)
        ):
            target = (last_name, last_bundled)
            for i in range(self._identification_config_combo.count()):
                data = self._identification_config_combo.itemData(i, Qt.ItemDataRole.UserRole)
                if data == target:
                    self._identification_config_combo.setCurrentIndex(i)
                    return

        # First launch, missing config, or unknown name → seed form with
        # PipelineOptions defaults and leave the combo on "— None —".
        self._apply_pipeline_options(PipelineOptions())

    def _save_session(self) -> None:
        test_mode = (
            self._test_mode_check.isChecked() if self._test_mode_check is not None else False
        )
        session = SessionConfig(
            last_folder=self._folder,
            last_pipeline_config_name=self._loaded_config_name,
            last_pipeline_config_bundled=self._loaded_config_bundled,
            test_mode=test_mode,
        )
        session.save(self._config_manager)

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def _set_folder(self, folder: Path, save: bool = True) -> None:
        if not folder.is_dir():
            return
        self._folder = folder
        self._folder_path_edit.setText(str(folder))
        self._images = sorted(
            p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
        )
        self._start_btn.setEnabled(bool(self._images))
        _log.debug("Folder set: %s (%d images)", folder, len(self._images))
        self._results_widget = None
        self._show_placeholder()
        if save:
            self._save_session()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_select_folder(self) -> None:
        if self._has_unconfirmed():
            reply = QMessageBox.question(
                self,
                "Select New Folder",
                "Not all results have been confirmed yet.\n"
                "Select a new folder and lose unconfirmed results?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        start = str(self._folder) if self._folder else ""
        folder_str = QFileDialog.getExistingDirectory(self, "Select Image Folder", start)
        if folder_str:
            self._set_folder(Path(folder_str))

    def _on_start_stop(self) -> None:
        if self._running:
            if self._has_unconfirmed():
                reply = QMessageBox.question(
                    self,
                    "Stop Processing",
                    "Batch is still running or results are not fully confirmed.\n"
                    "Stop and lose unconfirmed results?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            self._stop()
        else:
            if self._has_unconfirmed():
                reply = QMessageBox.question(
                    self,
                    "Start New Run",
                    "Not all results from the previous run have been confirmed.\n"
                    "Start a new run and lose unconfirmed results?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            self._start()

    def _on_config_toggled(self, checked: bool) -> None:
        self._apply_to_config_widgets(lambda w: w.setVisible(checked))

    def _on_identification_config_changed(self, index: int) -> None:
        """Load a saved identification config and apply all its settings to the form."""
        if not self._identification_config_combo or index < 0:
            return
        # Switching away discards any unsaved edits, so clear the previous
        # config's "(changed)" prefix before loading the new one.  Must
        # happen before self._loaded_config_name is overwritten below.
        if self._loaded_config_name is not None:
            self._set_config_item_display(
                self._loaded_config_name, self._loaded_config_bundled, is_dirty=False
            )
        entry = self._identification_config_combo.itemData(index, Qt.ItemDataRole.UserRole)
        if not entry:
            # "— None —" sentinel: drop loaded state but leave form values
            # alone so any in-progress edits are not lost.
            self._loaded_config = None
            self._loaded_config_name = None
            self._loaded_config_bundled = False
            self._loaded_config_snapshot = None
            self._dirty = False
            self._save_session()
            return

        name, is_bundled = entry
        try:
            config = self._config_store.load_config(name, bundled=is_bundled)
        except (FileNotFoundError, ValueError) as exc:
            _log.warning("Could not load identification config '%s': %s", name, exc)
            return

        self._loaded_config = config
        self._loaded_config_name = name
        self._loaded_config_bundled = is_bundled
        self._loaded_config_snapshot = config.to_dict()
        self._dirty = False
        self._update_changed_indicator()

        self._suspend_dirty_check = True
        try:
            # Apply pipeline selection.
            if self._pipeline_combo:
                from app.tools.scibit.core.pipeline import Pipeline

                cls = Pipeline.for_id(config.pipeline)
                if cls is not None:
                    p_idx = self._pipeline_combo.findData(cls)
                    if p_idx >= 0:
                        self._pipeline_combo.setCurrentIndex(p_idx)
            # Apply all pipeline-level options.
            self._apply_pipeline_options(config.pipeline_options)
        finally:
            self._suspend_dirty_check = False
        self._save_session()

    def _on_save_config_btn(self) -> None:
        """Prompt for a name and save the current configuration to disk."""
        default_name = self._loaded_config_name or ""
        name, ok = QInputDialog.getText(
            self, "Save Identification Config", "Configuration name:", text=default_name
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        config = self._build_configuration(config_name=name)
        if config is None:
            return
        try:
            self._config_store.save_config(config)
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return
        _log.info("Identification config '%s' saved.", name)

        # Refresh snapshot to the just-saved state and clear "(changed)".
        self._loaded_config = config
        self._loaded_config_name = name
        self._loaded_config_bundled = False
        self._loaded_config_snapshot = config.to_dict()
        self._dirty = False

        self._refresh_identification_config_combo(select=name, select_bundled=False)
        self._update_changed_indicator()
        self._save_session()

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    def _start(self) -> None:
        if not self._images:
            return

        config = self._build_configuration()
        if config is None:
            return

        self._configuration = config
        self._running = True
        self._start_btn.setText("Stop")
        self._set_control_bar_enabled(False)
        self._save_session()

        import app.tools.scibit.pipelines  # noqa: F401  (subclass registration)
        from app.tools.scibit.core.pipeline import Pipeline

        pipeline_cls = Pipeline.for_id(config.pipeline)
        if pipeline_cls is None:
            QMessageBox.critical(
                self,
                "Unknown Pipeline",
                f"No pipeline implementation found for '{config.pipeline}'.",
            )
            self._stop()
            return

        try:
            # No Qt parent — the pipeline gets moved to the batch worker
            # thread in _show_results_widget, which requires a parentless
            # QObject. Lifetime is managed via the Python reference plus
            # explicit cleanup() in _stop().
            self._current_pipeline = pipeline_cls.from_config(
                config, self._preset_registry, parent=None
            )
        except Exception as exc:
            QMessageBox.critical(self, "Pipeline Error", str(exc))
            self._stop()
            return

        # Capture per-batch results so the test-mode summary can read them
        # after batch completion. QueuedConnection is mandatory: the
        # pipeline emits from the batch worker thread, this slot must run
        # on the main thread.
        self._batch_results = []
        self._current_pipeline.batch_completed.connect(
            self._on_pipeline_batch_completed,
            Qt.ConnectionType.QueuedConnection,
        )

        self._t_run_start = time.monotonic()
        self._t_calib_done = None
        self._t_batch_done = None

        self._show_calibration_widget()

    def _on_pipeline_batch_completed(self, results: list[BatchResult]) -> None:
        """Stash the full result list for the test-mode accuracy summary."""
        if isinstance(results, list):
            self._batch_results = list(results)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop any running batch before the widget is destroyed.

        Without this, closing the tool while ``_batch_thread`` is still
        running causes a Qt fatal ("QThread: Destroyed while thread is
        still running") because the thread is a Qt child of this widget
        and gets destroyed alongside it.  ``_stop`` cancels the batch
        and joins the worker (briefly blocking the GUI while the
        current image finishes) before we let the close proceed.
        """
        if self._running or (self._batch_thread is not None and self._batch_thread.isRunning()):
            self._stop()
        super().closeEvent(event)

    def _stop(self) -> None:
        self._running = False
        self._calib_session = None
        self._results_widget = None
        self._calib_widget = None
        self._start_btn.setText("Start")
        self._start_btn.setEnabled(bool(self._images))
        self._set_control_bar_enabled(True)

        if self._batch_thread and self._batch_thread.isRunning():
            # Cooperative cancellation: the pipeline polls a flag between
            # images. quit() alone is a no-op here because run() doesn't
            # spin a Qt event loop. Wait long enough for one in-flight
            # image to finish (REQ-T1-016 targets ≤5s; 15s gives margin); if
            # it still hangs, force-terminate so the UI never freezes.
            self._batch_thread.cancel()
            if not self._batch_thread.wait(15_000):
                _log.warning("Batch thread did not stop within 15s — terminating.")
                self._batch_thread.terminate()
                self._batch_thread.wait()
        self._batch_thread = None
        if self._current_pipeline is not None:
            # cleanup() only touches the operator pool (plain Python +
            # release() on ML models) so it's safe to call from any
            # thread despite the pipeline's Qt affinity still pointing
            # at the stopped worker thread.
            self._current_pipeline.cleanup()
            self._current_pipeline = None
        # In-flight calibration changes are forfeited — clear the indicator.
        self._dirty = False
        self._update_changed_indicator()
        self._show_placeholder()

    def _show_calibration_widget(self) -> None:
        if not self._images or self._current_pipeline is None:
            return
        self._clear_process_area()

        widget = CalibrationWidget(parent=self._process_area_frame)
        widget.calibration_complete.connect(self._on_calibration_complete)
        widget.calibration_cancelled.connect(self._stop)
        widget.start_calibration(
            self._current_pipeline,
            self._images,
            self._configuration.pipeline_options,
            self._preset_registry,
        )

        self._calib_widget = widget
        self._process_area_frame.layout().addWidget(widget)
        # Save is unavailable while calibration is in progress.
        if self._save_config_btn:
            self._save_config_btn.setEnabled(False)

    def _on_calibration_complete(self, session: CalibrationSession) -> None:
        self._calib_session = session
        self._t_calib_done = time.monotonic()
        _log.info("Calibration complete.")
        # Re-enable saving for the duration of batch processing and review.
        if self._save_config_btn:
            self._save_config_btn.setEnabled(True)
        self._refresh_dirty_state()
        self._show_results_widget()

    def _show_results_widget(self) -> None:
        if self._current_pipeline is None or self._calib_session is None:
            return
        self._clear_process_area()

        widget = ResultsWidget(
            pipeline=self._current_pipeline,
            options=self._configuration.pipeline_options,
            image_folder=self._folder,
            session=self._calib_session,
            parent=self._process_area_frame,
        )
        widget.batch_complete.connect(self._on_batch_complete)
        self._results_widget = widget
        self._calib_widget = None
        self._process_area_frame.layout().addWidget(widget)

        # Run batch in a background thread. The pipeline is moved onto
        # the worker thread first so its signal emissions originate from
        # that thread's affinity — Qt then correctly queues them across
        # to main-thread receivers regardless of connection type.
        self._batch_thread = _BatchThread(
            self._current_pipeline,
            self._images,
            self._calib_session,
            parent=self,
        )
        self._current_pipeline.moveToThread(self._batch_thread)
        self._batch_thread.start()

    def _on_batch_complete(self) -> None:
        self._t_batch_done = time.monotonic()
        self._running = False
        self._start_btn.setText("Start")
        self._start_btn.setEnabled(bool(self._images))
        self._set_control_bar_enabled(True)
        self._log_timing_summary()
        if self._test_mode_check is not None and self._test_mode_check.isChecked():
            self._log_test_mode_summary()

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def _build_configuration(self, config_name: str | None = None) -> Configuration | None:
        """Build a Configuration from the current state.

        Stage configs come from the live pipeline when one exists (i.e.
        during/after calibration), otherwise from the most recently loaded
        identification config so an unmodified save round-trips correctly.

        Parameters
        ----------
        config_name : str | None
            Name stored in the resulting :class:`Configuration`.  Defaults to
            the loaded config's name or ``"(current)"`` if none.
        """
        pipeline_id = self._read_pipeline_id()
        stages = self._collect_stages_for_save()
        if config_name is None:
            config_name = self._loaded_config_name or "(current)"
        return Configuration(
            pipeline=pipeline_id,
            pipeline_options=self._read_pipeline_options(),
            stages=stages,
            name=config_name,
        )

    def _collect_stages_for_save(self) -> dict[str, StageConfig]:
        """Return stage configs to persist.

        Live pipeline state takes precedence; otherwise carry over the
        loaded config's stages so a no-op save preserves them.
        """
        if self._current_pipeline is not None:
            return {stage.name: stage.to_config() for stage in self._current_pipeline.get_stages()}
        if self._loaded_config is not None:
            return {
                name: StageConfig(operator=cfg.operator, parameters=dict(cfg.parameters))
                for name, cfg in self._loaded_config.stages.items()
            }
        return {}

    def _read_pipeline_id(self) -> str:
        """Return the pipeline ID selected in the pipeline combo.

        Falls back to the first registered pipeline class when no combo
        exists or it has no current selection.
        """
        if self._pipeline_combo:
            cls = self._pipeline_combo.currentData()
            if cls is not None:
                return cls.PIPELINE_ID
        import app.tools.scibit.pipelines  # noqa: F401  (subclass registration)
        from app.tools.scibit.core.pipeline import Pipeline

        registered = Pipeline.__subclasses__()
        return registered[0].PIPELINE_ID if registered else ""

    def _refresh_identification_config_combo(
        self, select: str | None = None, *, select_bundled: bool = False
    ) -> None:
        """Repopulate the identification config combo from disk.

        Parameters
        ----------
        select : str | None
            If given, selects the item whose canonical name matches.
        select_bundled : bool
            When ``select`` is given, disambiguates between a bundled and
            user entry of the same name.  ``False`` (default) selects the
            user version; ``True`` selects the bundled version.
        """
        if not self._identification_config_combo:
            return
        self._identification_config_combo.blockSignals(True)
        self._identification_config_combo.clear()
        self._identification_config_combo.addItem(_NO_IDENTIFICATION_CONFIG)
        self._identification_config_combo.setItemData(0, None, Qt.ItemDataRole.UserRole)
        for name, is_bundled in self._config_store.list_config_entries():
            display_name = _config_display_text(name, is_bundled)
            tooltip = (
                "Bundled configuration (read-only, cannot be edited)"
                if is_bundled
                else "User configuration"
            )
            self._identification_config_combo.addItem(display_name)
            idx = self._identification_config_combo.count() - 1
            self._identification_config_combo.setItemData(
                idx, (name, is_bundled), Qt.ItemDataRole.UserRole
            )
            self._identification_config_combo.setItemData(idx, tooltip, Qt.ItemDataRole.ToolTipRole)
        if select:
            target = (select, select_bundled)
            for i in range(1, self._identification_config_combo.count()):
                data = self._identification_config_combo.itemData(i, Qt.ItemDataRole.UserRole)
                if data == target:
                    self._identification_config_combo.setCurrentIndex(i)
                    break
        self._identification_config_combo.blockSignals(False)

    def _read_pipeline_options(self) -> PipelineOptions:
        preset_name = (
            self._preset_combo.currentText() if self._preset_combo else "Default (accept any)"
        )
        manual = (
            self._manual_confirmation_check.isChecked() if self._manual_confirmation_check else True
        )
        confidence = self._confidence_spin.value() if self._confidence_spin else 85.0
        debug_idx = self._debug_mode_combo.currentIndex() if self._debug_mode_combo else 0
        debug_mode = (
            _DEBUG_MODE_VALUES[debug_idx]
            if 0 <= debug_idx < len(_DEBUG_MODE_VALUES)
            else DebugExportMode.DISABLED
        )

        return PipelineOptions(
            identifier_pattern_preset=preset_name,
            manual_confirmation_required=manual,
            confidence_threshold_percent=confidence,
            debug_export_mode=debug_mode,
        )

    def _apply_pipeline_options(self, options: PipelineOptions) -> None:
        """Push *options* values into the form widgets."""
        if self._preset_combo:
            idx = self._preset_combo.findText(options.identifier_pattern_preset)
            if idx >= 0:
                self._preset_combo.setCurrentIndex(idx)
        if self._manual_confirmation_check:
            self._manual_confirmation_check.setChecked(options.manual_confirmation_required)
        if self._confidence_spin:
            self._confidence_spin.setValue(options.confidence_threshold_percent)
        if self._debug_mode_combo:
            try:
                idx = _DEBUG_MODE_VALUES.index(options.debug_export_mode)
                self._debug_mode_combo.setCurrentIndex(idx)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Timing
    # ------------------------------------------------------------------

    def _log_timing_summary(self) -> None:
        if self._t_run_start is None or self._t_calib_done is None or self._t_batch_done is None:
            _log.info("Batch processing complete.")
            return
        n = len(self._images)
        calib_secs = self._t_calib_done - self._t_run_start
        batch_secs = self._t_batch_done - self._t_calib_done
        avg_secs = batch_secs / n if n > 0 else 0.0
        _log.info(
            "Timing summary — Calibration: %.1f s | Batch: %.1f s | "
            "Images: %d | Avg per image: %.2f s",
            calib_secs,
            batch_secs,
            n,
            avg_secs,
        )

    def _log_test_mode_summary(self) -> None:
        """Compare each result against its source filename and log accuracy.

        Delegates the comparison to
        :func:`app.tools.scibit.core.accuracy.compute_filename_accuracy`;
        this method only formats and emits the log lines.
        """
        results = self._batch_results
        if not results:
            _log.info("Test mode: no batch results to evaluate.")
            return

        report = compute_filename_accuracy(results)
        _log.info(
            "Test mode — Accuracy: %d/%d (%.1f%%)",
            report.n_correct,
            report.total,
            report.accuracy,
        )
        _log.info("Test mode — Correct (%d): %s", report.n_correct, report.correct)
        _log.info(
            "Test mode — Wrong (%d): %s",
            len(report.wrong),
            [f"{fn} expected={exp!r} got={got!r}" for fn, exp, got in report.wrong],
        )

    # ------------------------------------------------------------------
    # Process area management
    # ------------------------------------------------------------------

    def _show_placeholder(self) -> None:
        self._clear_process_area()
        label = QLabel("Select a folder and press Start to begin.")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: gray; font-size: 14px;")
        self._process_area_frame.layout().addWidget(label)

    def _clear_process_area(self) -> None:
        layout = self._process_area_frame.layout()
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_dirty_state(self) -> None:
        """Recompute whether the live state has drifted from the loaded config.

        Diffs the loaded snapshot against a fresh :meth:`_build_configuration`
        and updates the combo display accordingly.  No-op when no config has
        been loaded.
        """
        if self._suspend_dirty_check:
            return
        if self._loaded_config_snapshot is None or self._loaded_config_name is None:
            return
        current = self._build_configuration(config_name=self._loaded_config_name)
        if current is None:
            return
        self._dirty = current.to_dict() != self._loaded_config_snapshot
        self._update_changed_indicator()

    def _set_config_item_display(self, name: str, is_bundled: bool, is_dirty: bool) -> None:
        """Set a combo item's display text for the given config entry.

        Finds the item whose UserRole matches ``(name, is_bundled)`` and
        rebuilds its text via :func:`_config_display_text`.  No-op when the
        item is not found (e.g. combo not built yet).
        """
        combo = self._identification_config_combo
        if not combo:
            return
        target = (name, is_bundled)
        idx = -1
        for i in range(combo.count()):
            if combo.itemData(i, Qt.ItemDataRole.UserRole) == target:
                idx = i
                break
        if idx < 0:
            return
        new_text = _config_display_text(name, is_bundled, is_dirty=is_dirty)
        if combo.itemText(idx) == new_text:
            return
        combo.blockSignals(True)
        combo.setItemText(idx, new_text)
        combo.blockSignals(False)

    def _update_changed_indicator(self) -> None:
        """Apply or remove the ``"(changed) "`` prefix on the loaded config's combo item.

        Preserves any existing ``"(bundled) "`` prefix — the display text
        is rebuilt from the stored ``(name, is_bundled)`` tuple plus the
        current dirty flag, never from the bare name alone.
        """
        if self._loaded_config_name is None:
            return
        self._set_config_item_display(
            self._loaded_config_name, self._loaded_config_bundled, self._dirty
        )

    def _has_unconfirmed(self) -> bool:
        if self._running:
            return True
        if self._results_widget is not None and self._results_widget.has_unconfirmed:
            return True
        return False

    def _apply_to_config_widgets(self, fn: Any) -> None:
        from PySide6.QtWidgets import QFormLayout

        if self._config_group is None:
            return
        form: QFormLayout = self._config_group.layout()
        for row in range(form.rowCount()):
            for role in (
                QFormLayout.ItemRole.LabelRole,
                QFormLayout.ItemRole.FieldRole,
                QFormLayout.ItemRole.SpanningRole,
            ):
                item = form.itemAt(row, role)
                if item is None:
                    continue
                if item.widget():
                    fn(item.widget())
                elif item.layout():
                    nested = item.layout()
                    for j in range(nested.count()):
                        child = nested.itemAt(j)
                        if child and child.widget():
                            fn(child.widget())

    def _set_control_bar_enabled(self, enabled: bool) -> None:
        if self._select_folder_btn:
            self._select_folder_btn.setEnabled(enabled)
        if self._identification_config_combo:
            self._identification_config_combo.setEnabled(enabled)
        if self._save_config_btn:
            self._save_config_btn.setEnabled(enabled)
        self._apply_to_config_widgets(lambda w: w.setEnabled(enabled))
