"""File Explorer base tool (REQ-HS-017)."""

from __future__ import annotations

import logging
import shutil
from abc import ABCMeta
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QModelIndex, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFileSystemModel,
    QInputDialog,
    QMenu,
    QMessageBox,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from app.core.config import ConfigManager
from app.plugin.base import IToolPlugin
from app.plugin.categories import ToolCategory

_logger = logging.getLogger("vi_toolbox.tools.file_explorer")

_CONFIG_KEY_ROOT = "root_dir"


# PySide6 uses Shiboken.ObjectType as QWidget's metaclass; ABCMeta is used by
# IBaseToolPlugin.  Combine both so Python's MRO does not raise a conflict.
class _FileExplorerMeta(type(QWidget), ABCMeta):
    pass


class FileExplorer(QWidget, IToolPlugin, metaclass=_FileExplorerMeta):
    """Self-contained file explorer tool widget.

    Displays a root directory tree and exposes all user interactions
    through a right-click context menu. Inherits from both
    :class:`~PySide6.QtWidgets.QWidget` and
    :class:`~app.plugin.base.IBaseToolPlugin` so that it can be embedded
    directly into the docking manager as its own content widget.

    Parameters
    ----------
    config_manager : ConfigManager
        Application-wide config manager used to persist the root directory
        between sessions.
    parent : QWidget | None
        Optional parent widget.
    """

    name: ClassVar[str] = "File Explorer"
    category: ClassVar[ToolCategory] = ToolCategory.BASE
    description: ClassVar[str] = "Browse and manage the working directory for VI postprocessing."
    icon_path: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"
    logger_name: ClassVar[str] = "vi_toolbox.tools.file_explorer"
    allow_multiple_instances: ClassVar[bool] = False
    closable: ClassVar[bool] = True

    current_root_dir: ClassVar[Path | None] = None

    # Emitted when the user picks "Open in <tool>" from the context menu.
    # MainWindow listens and opens a fresh tool instance, then calls open_from_path.
    open_tool_with_path_requested = Signal(str, object)  # (tool_name, path)

    def __init__(
        self,
        config_manager: ConfigManager,
        parent: QWidget | None = None,
    ) -> None:
        QWidget.__init__(self, parent)
        self._config_manager = config_manager
        self._setup_ui()
        QTimer.singleShot(0, self._load_root_from_config)

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

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model = QFileSystemModel(self)
        self._model.setRootPath("")

        self._tree = QTreeView(self)
        self._tree.setModel(self._model)
        self._tree.setHeaderHidden(True)
        self._tree.hideColumn(1)  # size
        self._tree.hideColumn(2)  # type
        self._tree.hideColumn(3)  # date modified
        # Disable built-in edit triggers; rename is context-menu only.
        self._tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.doubleClicked.connect(self._on_double_click)

        layout.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_root_from_config(self) -> None:
        cfg = self._config_manager.get_tool_config(self.name)
        raw = cfg.get(_CONFIG_KEY_ROOT)
        if raw:
            path = Path(raw)
            if path.exists():
                self._set_root_dir(path)
            else:
                _logger.error("Saved root directory no longer exists: %s", path)

    def _set_root_dir(self, path: Path) -> None:
        FileExplorer.current_root_dir = path
        root_index = self._model.setRootPath(str(path))
        self._tree.setRootIndex(root_index)
        cfg = self._config_manager.get_tool_config(self.name)
        cfg[_CONFIG_KEY_ROOT] = str(path)
        self._config_manager.set_tool_config(self.name, cfg)
        self._config_manager.save(self.name)
        _logger.debug("Root directory set to: %s", path)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _on_context_menu(self, pos: QPoint) -> None:
        index = self._tree.indexAt(pos)
        is_valid = index.isValid()
        path = Path(self._model.filePath(index)) if is_valid else None
        is_dir = path.is_dir() if path else False

        menu = QMenu(self)

        # Group 1 — always available
        act_change_root = menu.addAction("Change Root Directory")
        act_refresh = menu.addAction("Refresh")
        menu.addSeparator()

        # Group 2 — disabled when right-clicking empty space
        act_rename = menu.addAction("Rename")
        act_delete = menu.addAction("Delete")
        act_rename.setEnabled(is_valid)
        act_delete.setEnabled(is_valid)

        # Group 3 — folder items only
        act_new_file = act_new_folder = None
        if is_dir:
            menu.addSeparator()
            act_new_file = menu.addAction("New File")
            act_new_folder = menu.addAction("New Folder")

        # Group 4 — "Open in…" submenu built from registered tool classes
        # (no active instance required — each click opens a fresh instance).
        open_in_actions: dict[object, str] = {}
        if path is not None:
            from app.plugin.registry import (
                ToolRegistry,  # noqa: PLC0415 (lazy — avoids circular dep)
            )

            ext = path.suffix.lower()
            handlers = [
                (cls_name, tool_cls.name)
                for cls_name, tool_cls in ToolRegistry._registered_tools.items()
                if tool_cls is not type(self)
                and (
                    (path.is_dir() and getattr(tool_cls, "handles_folders", False))
                    or (
                        path.is_file()
                        and ext in getattr(tool_cls, "handled_path_extensions", frozenset())
                    )
                )
            ]
            if handlers:
                menu.addSeparator()
                open_in_menu = QMenu("Open in…", menu)
                for cls_name, display_name in handlers:
                    act = open_in_menu.addAction(display_name)
                    open_in_actions[act] = cls_name
                menu.addMenu(open_in_menu)

        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action is act_change_root:
            self._action_change_root()
        elif action is act_refresh:
            self._action_refresh()
        elif action is act_rename:
            self._action_rename(index)
        elif action is act_delete and path is not None:
            self._action_delete(path)
        elif action is act_new_file and path is not None:
            self._action_new_file(path)
        elif action is act_new_folder and path is not None:
            self._action_new_folder(path)
        elif action in open_in_actions and path is not None:
            self.open_tool_with_path_requested.emit(open_in_actions[action], path)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _action_change_root(self) -> None:
        start = str(FileExplorer.current_root_dir) if FileExplorer.current_root_dir else ""
        chosen = QFileDialog.getExistingDirectory(self, "Select Root Directory", start)
        if chosen:
            self._set_root_dir(Path(chosen))

    def _action_refresh(self) -> None:
        if FileExplorer.current_root_dir:
            root_index = self._model.setRootPath(str(FileExplorer.current_root_dir))
            self._tree.setRootIndex(root_index)
            _logger.debug("File explorer refreshed.")

    def _action_rename(self, index: QModelIndex) -> None:
        self._tree.edit(index)

    def _action_delete(self, path: Path) -> None:
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Permanently delete?\n\n{path}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            _logger.debug("Deleted: %s", path)
        except OSError as exc:
            _logger.error("Failed to delete '%s': %s", path, exc)
            QMessageBox.warning(self, "Delete Failed", f"Could not delete:\n{path}\n\n{exc}")

    def _action_new_file(self, folder: Path) -> None:
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if ok and name:
            try:
                (folder / name).touch()
            except OSError as exc:
                _logger.error("Failed to create file '%s': %s", folder / name, exc)

    def _action_new_folder(self, folder: Path) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            try:
                (folder / name).mkdir()
            except OSError as exc:
                _logger.error("Failed to create folder '%s': %s", folder / name, exc)

    def _on_double_click(self, index: QModelIndex) -> None:
        if not index.isValid() or not self._model.isDir(index):
            return
        if self._tree.isExpanded(index):
            self._collapse_recursive(index)
        else:
            self._tree.expand(index)
            for row in range(self._model.rowCount(index)):
                self._tree.expand(self._model.index(row, 0, index))

    def _collapse_recursive(self, index: QModelIndex) -> None:
        for row in range(self._model.rowCount(index)):
            self._collapse_recursive(self._model.index(row, 0, index))
        self._tree.collapse(index)
