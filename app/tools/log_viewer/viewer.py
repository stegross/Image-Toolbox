"""Log Viewer base tool (REQ-HS-017, REQ-HS-013)."""

from __future__ import annotations

import logging
from abc import ABCMeta
from typing import ClassVar

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

import app.core as _core_pkg
import app.plugin as _plugin_pkg
import app.shell as _shell_pkg
import app.tools as _tools_pkg
from app.core.config import ConfigManager
from app.core.logging import APP_LOGGER_NAME
from app.plugin.base import IToolPlugin
from app.plugin.categories import ToolCategory

_logger = logging.getLogger("vi_toolbox.tools.log_viewer")

_CONFIG_KEY_LEVEL = "log_level"
_CONFIG_KEY_SUBSYSTEM = "log_subsystem"

_MAX_LINES = 10_000

# Level labels and values derived from logging constants — no hardcoded strings.
_STANDARD_LEVELS = (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL)
_LEVEL_MAP: dict[str, int | None] = {"All": None} | {
    logging.getLevelName(lvl): lvl for lvl in _STANDARD_LEVELS
}
_LEVELS: list[str] = list(_LEVEL_MAP)


def _subsystem_entry(pkg: object) -> tuple[str, str]:
    """Derive a (label, logger-prefix) pair from a package's ``__name__``."""
    sub = pkg.__name__.rsplit(".", 1)[-1]  # type: ignore[union-attr]
    return sub.capitalize(), f"{APP_LOGGER_NAME}.{sub}"


# Per-level foreground colors — derived from the same _STANDARD_LEVELS tuple, no hardcoded ints.
# INFO maps to None so the default palette color is used (theme-neutral).
_LEVEL_COLORS: dict[int, QColor | None] = {
    logging.DEBUG: QColor(65, 65, 65),  # gray
    logging.INFO: None,  # default palette color
    logging.WARNING: QColor(220, 160, 0),  # amber
    logging.ERROR: QColor(200, 60, 60),  # red
    logging.CRITICAL: QColor(220, 30, 30),  # bright red
}

# Fixed subsystem entries derived from actual package names — no hardcoded subsystem strings.
_FIXED_SUBSYSTEMS: list[tuple[str, str | None]] = [
    ("All", None),
    _subsystem_entry(_core_pkg),
    _subsystem_entry(_shell_pkg),
    _subsystem_entry(_plugin_pkg),
    _subsystem_entry(_tools_pkg),
]


# ---------------------------------------------------------------------------
# Thread-safe logging bridge
# ---------------------------------------------------------------------------


class _LogSignalEmitter(QObject):
    """Emits log records as Qt signals so they can cross thread boundaries."""

    record_received = Signal(str, int, str)  # formatted message, levelno, logger name


class _LogOutputHandler(logging.Handler):
    """Forwards log records to a :class:`_LogSignalEmitter`."""

    def __init__(self, emitter: _LogSignalEmitter) -> None:
        super().__init__(logging.DEBUG)
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._emitter.record_received.emit(msg, record.levelno, record.name)
        except Exception:  # noqa: BLE001
            self.handleError(record)


# ---------------------------------------------------------------------------
# Widget metaclass (resolves PySide6 / ABCMeta conflict)
# ---------------------------------------------------------------------------


class _LogViewerMeta(type(QWidget), ABCMeta):
    pass


# ---------------------------------------------------------------------------
# LogViewer
# ---------------------------------------------------------------------------


class LogViewer(QWidget, IToolPlugin, metaclass=_LogViewerMeta):
    """Read-only log output viewer with level and subsystem filters.

    Captures every record emitted to the ``vi_toolbox`` logger (the same
    records written to the console and rotating file) and displays them in
    a scrollable, word-wrapped text area.  Two independent dropdowns allow
    the user to filter by minimum log level and by application subsystem.
    Both selections are persisted between sessions via :class:`ConfigManager`.

    Parameters
    ----------
    config_manager : ConfigManager
        Application-wide config manager used to persist filter selections.
    parent : QWidget | None
        Optional parent widget.
    """

    name: ClassVar[str] = "Log Viewer"
    category: ClassVar[ToolCategory] = ToolCategory.BASE
    description: ClassVar[str] = (
        "Displays application log output with level and subsystem filtering."
    )
    icon_path: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    logger_name: ClassVar[str] = "vi_toolbox.tools.log_viewer"
    allow_multiple_instances: ClassVar[bool] = False
    closable: ClassVar[bool] = True

    def __init__(
        self,
        config_manager: ConfigManager,
        parent: QWidget | None = None,
    ) -> None:
        QWidget.__init__(self, parent)
        self._config_manager = config_manager
        self._exact_level: int | None = None  # None = show all levels
        self._subsystem_prefix: str | None = None
        self._auto_scroll: bool = True

        self._emitter = _LogSignalEmitter(self)
        self._handler = _LogOutputHandler(self._emitter)
        self._handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

        # Buffer of every received record — filter is applied at display time.
        self._record_buffer: list[tuple[str, int, str]] = []  # (message, levelno, logger_name)

        self._setup_ui()
        self._load_config()

        self._emitter.record_received.connect(self._on_record)
        logging.getLogger(APP_LOGGER_NAME).addHandler(self._handler)

    # ------------------------------------------------------------------
    # IBaseToolPlugin interface
    # ------------------------------------------------------------------

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        """Return *self* as the dock widget content.

        Parameters
        ----------
        parent : QWidget | None
            Optional parent to re-assign.

        Returns
        -------
        QWidget
            This widget instance.
        """
        self.setParent(parent)
        return self

    def on_close(self) -> None:
        """Detach the log handler when the dock widget is closed."""
        logging.getLogger(APP_LOGGER_NAME).removeHandler(self._handler)

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Toolbar row
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        toolbar.addWidget(QLabel("Level:"))
        self._level_combo = QComboBox(self)
        self._level_combo.addItems(_LEVELS)
        self._level_combo.currentTextChanged.connect(self._on_level_changed)
        toolbar.addWidget(self._level_combo)

        toolbar.addWidget(QLabel("Subsystem:"))
        self._subsystem_combo = QComboBox(self)
        self._subsystem_map = self._build_subsystem_map()
        self._subsystem_combo.addItems(list(self._subsystem_map.keys()))
        self._subsystem_combo.currentTextChanged.connect(self._on_subsystem_changed)
        toolbar.addWidget(self._subsystem_combo)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Output area
        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        self._output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._output.setMaximumBlockCount(_MAX_LINES)
        self._output.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        layout.addWidget(self._output)

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _build_subsystem_map(self) -> dict[str, str | None]:
        """Build the label → logger-prefix map for the subsystem dropdown.

        Starts with the fixed entries from :data:`_FIXED_SUBSYSTEMS` and
        appends one entry per registered tool that declares a
        :attr:`~app.plugin.base.IToolPlugin.logger_name`.
        """
        from app.plugin.registry import ToolRegistry  # lazy import — avoids circular dep

        result: dict[str, str | None] = dict(_FIXED_SUBSYSTEMS)
        for tool_cls in ToolRegistry().get_all_tools():
            if tool_cls.logger_name:
                result[tool_cls.name] = tool_cls.logger_name
        return result

    def _load_config(self) -> None:
        cfg = self._config_manager.get_tool_config(self.name)
        level_str = cfg.get(_CONFIG_KEY_LEVEL, "All")
        subsystem_str = cfg.get(_CONFIG_KEY_SUBSYSTEM, "All")
        if level_str in _LEVELS:
            self._level_combo.setCurrentText(level_str)
        if subsystem_str in self._subsystem_map:
            self._subsystem_combo.setCurrentText(subsystem_str)

    def _save_config(self) -> None:
        cfg = self._config_manager.get_tool_config(self.name)
        cfg[_CONFIG_KEY_LEVEL] = self._level_combo.currentText()
        cfg[_CONFIG_KEY_SUBSYSTEM] = self._subsystem_combo.currentText()
        self._config_manager.set_tool_config(self.name, cfg)
        self._config_manager.save(self.name)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_level_changed(self, text: str) -> None:
        self._exact_level = _LEVEL_MAP.get(text)
        self._save_config()
        self._rebuild_output()

    def _on_subsystem_changed(self, text: str) -> None:
        self._subsystem_prefix = self._subsystem_map.get(text)
        self._save_config()
        self._rebuild_output()

    def _on_record(self, message: str, levelno: int, logger_name: str) -> None:
        self._record_buffer.append((message, levelno, logger_name))
        if len(self._record_buffer) > _MAX_LINES:
            self._record_buffer = self._record_buffer[-_MAX_LINES:]
        if not self._matches_filter(levelno, logger_name):
            return
        self._append_colored(message, levelno)
        if self._auto_scroll:
            scrollbar = self._output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _matches_filter(self, levelno: int, logger_name: str) -> bool:
        if self._exact_level is not None and levelno != self._exact_level:
            return False
        if self._subsystem_prefix and not logger_name.startswith(self._subsystem_prefix):
            return False
        return True

    def _rebuild_output(self) -> None:
        """Clear the display and re-render all buffered records through the current filter."""
        self._output.clear()
        for message, levelno, logger_name in self._record_buffer:
            if self._matches_filter(levelno, logger_name):
                self._append_colored(message, levelno)
        if self._auto_scroll:
            scrollbar = self._output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _append_colored(self, message: str, levelno: int) -> None:
        color = _LEVEL_COLORS.get(levelno)
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self._output.document().isEmpty():
            cursor.insertBlock()
        if color is not None:
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            cursor.setCharFormat(fmt)
        cursor.insertText(message)

    def _on_scroll_changed(self, value: int) -> None:
        scrollbar = self._output.verticalScrollBar()
        self._auto_scroll = value == scrollbar.maximum()
