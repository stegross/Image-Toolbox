"""Tests for the FileExplorer base tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from app.core.config import ConfigManager
from app.plugin.base import IToolPlugin
from app.plugin.categories import ToolCategory
from app.tools.base.file_explorer.explorer import FileExplorer
from PySide6.QtWidgets import QMessageBox, QWidget
from pytestqt.qtbot import QtBot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_manager(tmp_path: Path) -> ConfigManager:
    """Return a ConfigManager backed by a temporary directory."""
    return ConfigManager(tmp_path / "config")


@pytest.fixture()
def explorer(qtbot: QtBot, config_manager: ConfigManager) -> FileExplorer:
    """Return a FileExplorer with no pre-configured root."""
    widget = FileExplorer(config_manager)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture(autouse=True)
def reset_class_state() -> None:
    """Reset FileExplorer class-level state between tests."""
    FileExplorer.current_root_dir = None
    yield
    FileExplorer.current_root_dir = None


# ---------------------------------------------------------------------------
# Class attributes
# ---------------------------------------------------------------------------


class TestFileExplorerClassAttributes:
    """Verify IToolPlugin contract and FileExplorer class attributes."""

    def test_name(self) -> None:
        """Name class attribute equals 'File Explorer'."""
        assert FileExplorer.name == "File Explorer"

    def test_category(self) -> None:
        """Category value equals ToolCategory.BASE value.

        Compare by value: Shiboken's Qt metatype registration modifies
        ToolCategory's EnumMeta when FileExplorer is defined, making direct
        member access (ToolCategory.BASE) unreliable inside the test process.
        """
        assert FileExplorer.category.value == ToolCategory.BASE.value

    def test_allow_multiple_instances_false(self) -> None:
        """allow_multiple_instances is False (only one instance allowed)."""
        assert FileExplorer.allow_multiple_instances is False

    def test_closable_true(self) -> None:
        """Closable is True (user can close the dock widget)."""
        assert FileExplorer.closable is True

    def test_is_itooplplugin_subclass(self) -> None:
        """FileExplorer is a subclass of IToolPlugin."""
        assert issubclass(FileExplorer, IToolPlugin)


# ---------------------------------------------------------------------------
# Widget identity
# ---------------------------------------------------------------------------


class TestFileExplorerWidget:
    """Verify the widget is self-contained and create_widget returns self."""

    def test_is_qwidget(self, explorer: FileExplorer) -> None:
        """FileExplorer instance is a QWidget."""
        assert isinstance(explorer, QWidget)

    def test_create_widget_returns_self(self, explorer: FileExplorer) -> None:
        """create_widget returns the FileExplorer instance itself."""
        assert explorer.create_widget() is explorer

    def test_create_widget_sets_parent(self, qtbot: QtBot, config_manager: ConfigManager) -> None:
        """create_widget re-assigns the given parent widget."""
        parent = QWidget()
        qtbot.addWidget(parent)
        widget = FileExplorer(config_manager)
        qtbot.addWidget(widget)
        widget.create_widget(parent)
        assert widget.parent() is parent


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------


class TestFileExplorerConfig:
    """Verify root directory is persisted and restored via ConfigManager."""

    def test_set_root_updates_class_var(self, explorer: FileExplorer, tmp_path: Path) -> None:
        """_set_root_dir updates the current_root_dir class variable."""
        explorer._set_root_dir(tmp_path)
        assert FileExplorer.current_root_dir == tmp_path

    def test_set_root_saves_to_config(
        self, explorer: FileExplorer, config_manager: ConfigManager, tmp_path: Path
    ) -> None:
        """_set_root_dir persists the path to ConfigManager."""
        explorer._set_root_dir(tmp_path)
        cfg = config_manager.get_tool_config("File Explorer")
        assert cfg["root_dir"] == str(tmp_path)

    def test_root_loaded_on_init(
        self, qtbot: QtBot, config_manager: ConfigManager, tmp_path: Path
    ) -> None:
        """Root directory from config is applied automatically on construction."""
        config_manager.set_tool_config("File Explorer", {"root_dir": str(tmp_path)})
        config_manager.save("File Explorer")

        widget = FileExplorer(config_manager)
        qtbot.addWidget(widget)

        assert FileExplorer.current_root_dir == tmp_path

    def test_invalid_root_in_config_is_ignored(
        self, qtbot: QtBot, config_manager: ConfigManager
    ) -> None:
        """A non-existent root path in config does not crash and is skipped."""
        config_manager.set_tool_config("File Explorer", {"root_dir": "/nonexistent/path/xyz"})
        config_manager.save("File Explorer")

        widget = FileExplorer(config_manager)
        qtbot.addWidget(widget)

        assert FileExplorer.current_root_dir is None


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


class TestFileExplorerActions:
    """Verify context-menu action behaviour."""

    def test_action_new_file_creates_file(self, explorer: FileExplorer, tmp_path: Path) -> None:
        """New File action creates a file with the given name in the folder."""
        with patch(
            "app.tools.base.file_explorer.explorer.QInputDialog.getText",
            return_value=("test.txt", True),
        ):
            explorer._action_new_file(tmp_path)

        assert (tmp_path / "test.txt").is_file()

    def test_action_new_file_cancelled_creates_nothing(
        self, explorer: FileExplorer, tmp_path: Path
    ) -> None:
        """Cancelling New File dialog leaves the directory unchanged."""
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        with patch(
            "app.tools.base.file_explorer.explorer.QInputDialog.getText",
            return_value=("", False),
        ):
            explorer._action_new_file(target_dir)

        assert list(target_dir.iterdir()) == []

    def test_action_new_folder_creates_directory(
        self, explorer: FileExplorer, tmp_path: Path
    ) -> None:
        """New Folder action creates a subdirectory with the given name."""
        with patch(
            "app.tools.base.file_explorer.explorer.QInputDialog.getText",
            return_value=("subdir", True),
        ):
            explorer._action_new_folder(tmp_path)

        assert (tmp_path / "subdir").is_dir()

    def test_action_delete_file_with_confirmation(
        self, explorer: FileExplorer, tmp_path: Path
    ) -> None:
        """Delete action removes a file when the user confirms."""
        target = tmp_path / "to_delete.txt"
        target.touch()

        with patch(
            "app.tools.base.file_explorer.explorer.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            explorer._action_delete(target)

        assert not target.exists()

    def test_action_delete_cancelled_keeps_file(
        self, explorer: FileExplorer, tmp_path: Path
    ) -> None:
        """Delete action leaves the file intact when the user cancels."""
        target = tmp_path / "keep_me.txt"
        target.touch()

        with patch(
            "app.tools.base.file_explorer.explorer.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ):
            explorer._action_delete(target)

        assert target.exists()

    def test_action_delete_nonempty_directory(self, explorer: FileExplorer, tmp_path: Path) -> None:
        """Delete action removes a non-empty directory tree when confirmed."""
        folder = tmp_path / "folder"
        folder.mkdir()
        (folder / "child.txt").touch()

        with patch(
            "app.tools.base.file_explorer.explorer.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            explorer._action_delete(folder)

        assert not folder.exists()

    def test_action_refresh_does_not_raise(self, explorer: FileExplorer, tmp_path: Path) -> None:
        """Refresh action completes without raising an exception."""
        explorer._set_root_dir(tmp_path)
        explorer._action_refresh()

    def test_action_change_root_updates_root(self, explorer: FileExplorer, tmp_path: Path) -> None:
        """Change Root Directory sets current_root_dir to the chosen path."""
        with patch(
            "app.tools.base.file_explorer.explorer.QFileDialog.getExistingDirectory",
            return_value=str(tmp_path),
        ):
            explorer._action_change_root()

        assert FileExplorer.current_root_dir == tmp_path

    def test_action_change_root_cancelled_no_change(self, explorer: FileExplorer) -> None:
        """Cancelling the Change Root dialog leaves current_root_dir unchanged."""
        with patch(
            "app.tools.base.file_explorer.explorer.QFileDialog.getExistingDirectory",
            return_value="",
        ):
            explorer._action_change_root()

        assert FileExplorer.current_root_dir is None
