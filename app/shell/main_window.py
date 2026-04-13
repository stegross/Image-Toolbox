"""Main application window (REQ-HS-001, REQ-HS-004, REQ-HS-007)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QWidget
from PySide6QtAds import CDockManager

from app.core.config import ConfigManager
from app.core.roles import RoleManager
from app.plugin.registry import ToolRegistry
from app.shell.docking_manager import DockingManager
from app.shell.layout import LayoutPersistence
from app.shell.ui.ui_main_window import Ui_MainWindow

_logger = logging.getLogger("vi_toolbox.shell.main_window")

_LOG_DIR = Path.home() / ".vi_toolbox" / "logs"


class MainWindow(QMainWindow):
    """Top-level application window for VI-Toolbox.

    Owns the docking area, menu bar, and all currently open tool widgets.
    Delegates layout persistence to
    :class:`~app.shell.layout.LayoutPersistence` and tool lifecycle to
    :class:`~app.plugin.registry.ToolRegistry`.

    Parameters
    ----------
    tool_registry : ToolRegistry
        Shared registry of all registered tool classes.
    role_manager : RoleManager
        Used to check permissions before opening a tool.
    config_manager : ConfigManager
        Used to load per-tool configs and save them on shutdown.
    layout_persistence : LayoutPersistence
        Handles saving/restoring the dock layout between sessions.
    parent : QWidget | None
        Optional parent widget.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        role_manager: RoleManager,
        config_manager: ConfigManager,
        layout_persistence: LayoutPersistence,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool_registry = tool_registry
        self._role_manager = role_manager
        self._config_manager = config_manager
        self._layout_persistence = layout_persistence

        self.initialize()

    def initialize(self) -> None:
        """Build the UI, restore layout, and open base tools.

        Called once by :meth:`__init__`.  Sequence:

        1. Set Qt ADS config flags (must happen before ``CDockManager`` is
           created inside ``setupUi``).
        2. Load the ``.ui`` file — creates the ``CDockManager`` and menu bar.
        3. Wrap the dock manager.
        4. Connect static menu actions and build dynamic category menus.
        5. Restore previously saved layout (REQ-HS-007).
        6. Open all base tools automatically.
        """
        # Config flags must be set before CDockManager is instantiated
        CDockManager.setConfigFlag(CDockManager.eConfigFlag.DockAreaHasUndockButton, False)
        CDockManager.setConfigFlag(CDockManager.eConfigFlag.DockAreaHasTabsMenuButton, False)
        CDockManager.setConfigFlag(CDockManager.eConfigFlag.FocusHighlighting, True)

        # Load the .ui file (creates dockManager and the Application menu bar)
        self._ui = Ui_MainWindow()
        self._ui.setupUi(self)

        # Wrap the CDockManager created by setupUi
        self._docking_manager = DockingManager(self._ui.dockManager)

        # Connect static Application-menu actions
        self._ui.actionOpenLogFolder.triggered.connect(lambda: self._open_log_folder())
        self._ui.actionAbout.triggered.connect(lambda: _logger.info("About: VI-Toolbox v0.1.0"))

        # Insert tool-button actions and build dynamic category menus
        self._build_category_menus()

        # Ordered map of instance_key → tool_name for every currently open tool.
        # Maintained by open_tool / _on_tool_closed to build the session snapshot.
        self._open_instance_names: dict[str, str] = {}

        # If a session was previously saved, restore those exact tool instances (in
        # order) so instance keys match what Qt ADS persisted.  Otherwise fall back
        # to the hardcoded default layout (auto_open_on_startup tools + default size).
        saved_tools = self._layout_persistence.load_open_tools()
        if saved_tools is not None:
            for tool_name in saved_tools:
                self.open_tool(tool_name)
            self.restore_layout()
        else:
            self._open_default_layout()

        _logger.info("MainWindow initialised.")

    def open_tool(self, name: str) -> QWidget | None:
        """Open a tool by name, respecting instance and permission rules.

        If *name* is already instantiated and ``allow_multiple_instances``
        is ``False``, the existing dock widget is focused instead and ``None``
        is returned.  Otherwise the new widget is returned so callers can
        perform post-open operations (e.g. call ``open_from_path``).

        Parameters
        ----------
        name : str
            Tool name as registered in
            :class:`~app.plugin.registry.ToolRegistry`.

        Returns
        -------
        QWidget | None
            The newly created widget, or ``None`` when an existing instance
            was focused.
        """
        try:
            tool_cls = self._tool_registry.get_tool(name)
        except KeyError:
            _logger.error("open_tool: unknown tool '%s'", name)
            return None

        already_open = self._tool_registry.is_instantiated(name)
        allow_multiple = getattr(tool_cls, "allow_multiple_instances", False)

        if already_open and not allow_multiple:
            _logger.debug("Tool '%s' already open — focusing existing widget.", name)
            self._docking_manager.focus_widget(name)
            return None

        if not self._role_manager.has_permission(name):
            _logger.warning("Access denied: user has no permission for '%s'.", name)
            return None

        instance_key, instance_id = self._tool_registry.allocate_instance_key(name, allow_multiple)

        tool_instance = tool_cls(self._config_manager)
        tool_instance._assign_instance_id(instance_id)
        widget = tool_instance.create_widget(self)
        closable = getattr(tool_cls, "closable", True)

        self._open_instance_names[instance_key] = name

        def _on_tool_closed() -> None:
            tool_instance.on_close()
            self._tool_registry.remove_instance(instance_key)
            self._open_instance_names.pop(instance_key, None)
            _logger.info("Tool closed: %s", instance_key)

        self._docking_manager.add_tool_widget(
            instance_key, widget, closable=closable, on_close=_on_tool_closed
        )
        self._tool_registry.set_instance(instance_key, widget)
        if hasattr(widget, "open_tool_with_path_requested"):
            widget.open_tool_with_path_requested.connect(self._on_open_tool_with_path)
        tool_instance.on_activate()

        _logger.info("Tool opened: %s", instance_key)
        return widget

    def close_tool(self, name: str) -> None:
        """Close and remove a tool widget from the dock area.

        Parameters
        ----------
        name : str
            Tool name.
        """
        self._docking_manager.remove_tool_widget(name)
        self._tool_registry.remove_instance(name)
        _logger.info("Tool closed: %s", name)

    def save_layout(self) -> None:
        """Serialise and persist the current dock layout."""
        state = self._docking_manager.save_state()
        self._layout_persistence.save(state)

    def restore_layout(self) -> None:
        """Restore the dock layout and window geometry from the last saved session (REQ-HS-007)."""
        geometry = self._layout_persistence.load_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
            _logger.info("Window geometry restored from previous session.")

        state = self._layout_persistence.load()
        if state is not None:
            self._docking_manager.restore_state(state)
            _logger.info("Layout restored from previous session.")
        else:
            _logger.info("No saved layout found — using default.")

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Handle window close: save configs and layout, then quit.

        Parameters
        ----------
        event : QCloseEvent
            The close event from Qt.
        """
        _logger.info("Shutdown initiated.")
        self._config_manager.save_all()
        self._config_manager.save_all_instances()
        self._layout_persistence.save_open_tools(list(self._open_instance_names.values()))
        self._layout_persistence.save_geometry(self.saveGeometry())
        self.save_layout()
        event.accept()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_category_menus(self) -> None:
        """Populate the menu bar with a top-level menu for each tool category.

        Each registered category gets its own :class:`QMenu` appended to the
        menu bar after the static *Application* menu defined in the ``.ui``
        file.  The *Application* menu itself is left unchanged (it contains
        only Open Log Folder and About).
        """
        for category in self._tool_registry.get_all_categories():
            tools = self._tool_registry.get_tools_by_category(category)
            if not tools:
                continue

            menu = self.menuBar().addMenu(category.value)
            for tool_cls in tools:
                action = menu.addAction(tool_cls.name)
                action.setToolTip(tool_cls.description)
                action.triggered.connect(lambda _checked=False, n=tool_cls.name: self.open_tool(n))

        _logger.debug(
            "Category menus built: %d categories registered.",
            len(self._tool_registry.get_all_categories()),
        )

    def _open_default_layout(self) -> None:
        """Apply the hardcoded default layout for first-time startup.

        Opens all tools with ``auto_open_on_startup = True`` and sets a
        sensible default window size.  Only called when no saved session
        exists (e.g. very first launch or after the state files are deleted).
        """
        self.resize(1400, 900)
        for tool_cls in self._tool_registry.get_auto_open_tools():
            self.open_tool(tool_cls.name)

    def _on_open_tool_with_path(self, tool_name: str, path: object) -> None:
        """Open a fresh instance of *tool_name* and load *path* into it.

        Parameters
        ----------
        tool_name : str
            Registered tool name.
        path : object
            A :class:`~pathlib.Path` instance forwarded from the emitting tool.
        """
        widget = self.open_tool(tool_name)
        if widget is not None and hasattr(widget, "open_from_path"):
            widget.open_from_path(path)

    def _open_log_folder(self) -> None:
        """Open the application log folder in Windows Explorer."""
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(_LOG_DIR))  # Windows only (REQ-EC-004)
