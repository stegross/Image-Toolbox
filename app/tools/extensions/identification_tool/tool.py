"""SCIBIT — Single Chip Image Batch Identification Tool plugin."""

from __future__ import annotations

import logging
from abc import ABCMeta
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QFile, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.config import ConfigManager
from app.plugin.base import IBaseToolPlugin
from app.plugin.categories import ToolCategory
from app.tools.extensions.identification_tool.config import (
    DETECTION_FRAMEWORKS,
    OCR_FRAMEWORKS,
    load_identifier_configs,
)
from app.tools.extensions.identification_tool.ocr.factory import create_engine
from app.tools.extensions.identification_tool.pipeline.base import AbstractPipeline, CalibrationData
from app.tools.extensions.identification_tool.pipeline.pipeline1 import Pipeline1
from app.tools.extensions.identification_tool.pipeline.pipeline2 import Pipeline2
from app.tools.extensions.identification_tool.ui.calibration import CalibrationWidget
from app.tools.extensions.identification_tool.ui.results import ResultsWidget

_logger = logging.getLogger("vi_toolbox.tools.scibit")

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png"})

# Config keys
_CFG_FOLDER = "last_folder"
_CFG_CHIP_TYPE = "chip_type_index"
_CFG_PIPELINE = "pipeline_index"
_CFG_DETECTION = "detection_framework_index"
_CFG_OCR = "ocr_framework_index"
_CFG_MIN_CONF = "min_confidence"
_CFG_RENAME_PREVIEW = "rename_preview"
_CFG_CONFIG_EXPANDED = "config_expanded"


# ---------------------------------------------------------------------------
# Metaclass shim (QWidget + ABCMeta conflict)
# ---------------------------------------------------------------------------


class _SciBitMeta(type(QWidget), ABCMeta):
    pass


# ---------------------------------------------------------------------------
# SciBitTool
# ---------------------------------------------------------------------------


class SciBitTool(QWidget, IBaseToolPlugin, metaclass=_SciBitMeta):
    """Single Chip Image Batch Identification Tool.

    Processes a folder of chip images, recognises the identifier printed on
    each chip via OCR, and renames the files accordingly.  Low-confidence
    results are queued for manual review.

    Parameters
    ----------
    config_manager : ConfigManager
        Application-wide config manager used to persist UI settings.
    parent : QWidget | None
        Optional parent widget.
    """

    name: ClassVar[str] = "SCIBIT"
    category: ClassVar[ToolCategory] = ToolCategory.IDENTIFICATION
    description: ClassVar[str] = "Single Chip Image Batch Identification Tool"
    icon_path: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    logger_name: ClassVar[str] = "vi_toolbox.tools.scibit"
    auto_open_on_startup: ClassVar[bool] = False
    allow_multiple_instances: ClassVar[bool] = False
    closable: ClassVar[bool] = True
    handles_folders: ClassVar[bool] = True
    handled_path_extensions: ClassVar[frozenset[str]] = frozenset()  # no individual file handling

    def __init__(
        self,
        config_manager: ConfigManager,
        parent: QWidget | None = None,
    ) -> None:
        QWidget.__init__(self, parent)
        self._config_manager = config_manager
        self._folder: Path | None = None
        self._images: list[Path] = []
        self._running = False
        self._current_pipeline: AbstractPipeline | None = None
        self._calib_data: CalibrationData | None = None
        self._logger = _logger

        self._setup_ui()
        self._populate_combos()
        self._load_config()

    # ------------------------------------------------------------------
    # IToolPlugin interface
    # ------------------------------------------------------------------

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        self.setParent(parent)
        return self

    def _assign_instance_id(self, instance_id: int) -> None:
        super()._assign_instance_id(instance_id)
        self._logger = logging.getLogger(f"{self.logger_name}.{instance_id}")

    def accepts_path(self, path: Path) -> bool:
        return path.is_dir()

    def open_from_path(self, path: Path) -> None:
        if path.is_dir():
            self._set_folder(path)

    # ------------------------------------------------------------------
    # UI setup (loads tool.ui)
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        ui_path = Path(__file__).parent / "tool.ui"
        loader = QUiLoader()
        ui_file = QFile(str(ui_path))
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            self._logger.error("Cannot open tool.ui: %s", ui_path)
            outer.addWidget(QLabel("Error: tool.ui not found.", self))
            return

        self._form = loader.load(ui_file, self)
        ui_file.close()

        if self._form is None:
            self._logger.error("QUiLoader failed to load tool.ui")
            outer.addWidget(QLabel("Error loading UI.", self))
            return

        outer.addWidget(self._form)

        # -- Retrieve widget references by object name --
        self._select_folder_btn: QPushButton = self._form.findChild(QPushButton, "select_folder_btn")
        self._folder_path_edit: QLineEdit = self._form.findChild(QLineEdit, "folder_path_edit")
        self._start_btn: QPushButton = self._form.findChild(QPushButton, "start_btn")
        self._config_group = self._form.findChild(QWidget, "config_group")
        self._chip_type_combo: QComboBox = self._form.findChild(QComboBox, "chip_type_combo")
        self._pipeline_combo: QComboBox = self._form.findChild(QComboBox, "pipeline_combo")
        self._detection_framework_combo: QComboBox = self._form.findChild(QComboBox, "detection_framework_combo")
        self._ocr_framework_combo: QComboBox = self._form.findChild(QComboBox, "ocr_framework_combo")
        self._min_confidence_spin: QDoubleSpinBox = self._form.findChild(QDoubleSpinBox, "min_confidence_spin")
        self._rename_preview_check: QCheckBox = self._form.findChild(QCheckBox, "rename_preview_check")
        self._process_area_frame: QFrame = self._form.findChild(QFrame, "process_area_frame")

        # -- Connect control bar signals --
        self._select_folder_btn.clicked.connect(self._on_select_folder)
        self._start_btn.clicked.connect(self._on_start_stop)

        # Style the placeholder
        placeholder = self._process_area_frame.findChild(QLabel, "process_placeholder_label")
        if placeholder:
            placeholder.setStyleSheet("color: gray; font-size: 14px;")

    # ------------------------------------------------------------------
    # Combo population
    # ------------------------------------------------------------------

    def _populate_combos(self) -> None:
        if self._chip_type_combo is None:
            return
        configs = load_identifier_configs(self._config_manager._config_dir)
        self._chip_type_combo.clear()
        for cfg in configs:
            self._chip_type_combo.addItem(cfg.name)

        self._detection_framework_combo.clear()
        for name in DETECTION_FRAMEWORKS:
            self._detection_framework_combo.addItem(name)

        self._ocr_framework_combo.clear()
        for name in OCR_FRAMEWORKS:
            self._ocr_framework_combo.addItem(name)

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self) -> None:
        cfg = self._config_manager.get_tool_config(self.name)
        folder_str = cfg.get(_CFG_FOLDER, "")
        if folder_str:
            self._set_folder(Path(folder_str), save=False)
        if self._chip_type_combo:
            self._chip_type_combo.setCurrentIndex(cfg.get(_CFG_CHIP_TYPE, 0))
            self._pipeline_combo.setCurrentIndex(cfg.get(_CFG_PIPELINE, 0))
            self._detection_framework_combo.setCurrentIndex(cfg.get(_CFG_DETECTION, 0))
            self._ocr_framework_combo.setCurrentIndex(cfg.get(_CFG_OCR, 0))
            self._min_confidence_spin.setValue(cfg.get(_CFG_MIN_CONF, 0.75))
            self._rename_preview_check.setChecked(cfg.get(_CFG_RENAME_PREVIEW, False))

    def _save_config(self) -> None:
        cfg = self._config_manager.get_tool_config(self.name)
        cfg[_CFG_FOLDER] = str(self._folder) if self._folder else ""
        if self._chip_type_combo:
            cfg[_CFG_CHIP_TYPE] = self._chip_type_combo.currentIndex()
            cfg[_CFG_PIPELINE] = self._pipeline_combo.currentIndex()
            cfg[_CFG_DETECTION] = self._detection_framework_combo.currentIndex()
            cfg[_CFG_OCR] = self._ocr_framework_combo.currentIndex()
            cfg[_CFG_MIN_CONF] = self._min_confidence_spin.value()
            cfg[_CFG_RENAME_PREVIEW] = self._rename_preview_check.isChecked()
        self._config_manager.set_tool_config(self.name, cfg)
        self._config_manager.save(self.name)

    # ------------------------------------------------------------------
    # IToolPlugin lifecycle
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        self._save_config()
        if self._current_pipeline:
            self._current_pipeline.stop()

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def _set_folder(self, folder: Path, save: bool = True) -> None:
        if not folder.is_dir():
            return
        self._folder = folder
        self._folder_path_edit.setText(str(folder))
        self._images = sorted(
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
        )
        self._start_btn.setEnabled(bool(self._images))
        self._logger.debug("Folder set: %s (%d images)", folder, len(self._images))
        if save:
            self._save_config()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_select_folder(self) -> None:
        start = str(self._folder) if self._folder else ""
        folder_str = QFileDialog.getExistingDirectory(self, "Select Image Folder", start)
        if folder_str:
            self._set_folder(Path(folder_str))

    def _on_start_stop(self) -> None:
        if self._running:
            self._stop()
        else:
            self._start()

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    def _start(self) -> None:
        if not self._images:
            return
        self._running = True
        self._start_btn.setText("Stop")
        self._set_control_bar_enabled(False)
        self._save_config()

        # Build OCR engines from combo selections
        detection_name = self._detection_framework_combo.currentText() if self._detection_framework_combo else "Tesseract"
        ocr_name = self._ocr_framework_combo.currentText() if self._ocr_framework_combo else "Tesseract"
        try:
            detection_engine = create_engine(detection_name)
            # Reuse the same instance if both combos select the same framework
            recognition_engine = detection_engine if ocr_name == detection_name else create_engine(ocr_name)
        except (ImportError, RuntimeError, ValueError) as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "OCR Engine Error", str(exc))
            self._stop()
            return

        # Build pipeline
        pipeline_index = self._pipeline_combo.currentIndex() if self._pipeline_combo else 0
        if pipeline_index == 0:
            self._current_pipeline = Pipeline1(detection_engine, recognition_engine, self)
        else:
            self._current_pipeline = Pipeline2(detection_engine, recognition_engine, self)

        # Show calibration widget
        self._show_calibration_widget()

    def _stop(self) -> None:
        self._running = False
        self._start_btn.setText("Start")
        self._start_btn.setEnabled(bool(self._images))
        self._set_control_bar_enabled(True)
        if self._current_pipeline:
            self._current_pipeline.stop()
            self._current_pipeline = None
        self._show_placeholder()

    def _show_calibration_widget(self) -> None:
        if not self._images or self._current_pipeline is None:
            return
        self._clear_process_area()
        widget = CalibrationWidget(
            pipeline=self._current_pipeline,
            image_path=self._images[0],
            parent=self._process_area_frame,
        )
        widget.calibration_complete.connect(self._on_calibration_complete)
        widget.calibration_cancelled.connect(self._stop)
        self._process_area_frame.layout().addWidget(widget)

    def _on_calibration_complete(self, calib_data: CalibrationData) -> None:
        self._calib_data = calib_data
        self._logger.info(
            "Calibration complete. Reference identifier: %s", calib_data.reference_identifier
        )
        self._show_results_widget()

    def _show_results_widget(self) -> None:
        if self._current_pipeline is None or self._calib_data is None:
            return
        self._clear_process_area()
        widget = ResultsWidget(
            pipeline=self._current_pipeline,
            parent=self._process_area_frame,
        )
        widget.batch_complete.connect(self._on_batch_complete)
        self._process_area_frame.layout().addWidget(widget)

        # Exclude reference image from batch
        batch_images = self._images[1:]
        min_conf = self._min_confidence_spin.value() if self._min_confidence_spin else 0.75
        self._current_pipeline.start_batch(batch_images, self._calib_data, min_conf)

    def _on_batch_complete(self) -> None:
        self._running = False
        self._start_btn.setText("Start")
        self._start_btn.setEnabled(bool(self._images))
        self._set_control_bar_enabled(True)
        self._logger.info("Batch processing complete.")

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

    def _set_control_bar_enabled(self, enabled: bool) -> None:
        """Enable/disable all control bar widgets except the Start/Stop button."""
        if self._select_folder_btn:
            self._select_folder_btn.setEnabled(enabled)
        if self._config_group:
            self._config_group.setEnabled(enabled)
