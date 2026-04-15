"""Abstract base classes for all tool plugins."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from PySide6.QtWidgets import QWidget

from app.plugin.categories import ToolCategory


class IToolPlugin(ABC):
    """Abstract interface that every tool plugin must implement.

    All tools — both base tools and extension tools — must subclass this
    class and provide the required class attributes and the
    :meth:`create_widget` method.

    Attributes
    ----------
    name : str
        Unique tool name used as the registry key and dock widget title.
    category : ToolCategory
        Navigation menu category this tool belongs to.
    description : str
        Short human-readable description shown in the UI.
    icon_path : str
        Path to the tool icon relative to the project root.
        Use an empty string if no icon is available.
    version : str
        Tool version string (e.g. ``"1.0.0"``).
    """

    name: ClassVar[str]
    category: ClassVar[ToolCategory]
    description: ClassVar[str]
    icon_path: ClassVar[str]
    version: ClassVar[str]
    logger_name: ClassVar[str] = ""  # dotted logger name, e.g. "vi_toolbox.tools.file_explorer"
    # Path-handling capability — used by the File Explorer to build the
    # "Open in…" context menu without needing an active instance.
    handled_path_extensions: ClassVar[frozenset[str]] = frozenset()
    handles_folders: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Validate that concrete subclasses define all required class attributes."""
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            for attr in ("name", "category", "description", "version"):
                if not hasattr(cls, attr):
                    raise TypeError(f"{cls.__name__} must define class attribute '{attr}'")

    @abstractmethod
    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        """Create and return the tool's main content widget.

        Parameters
        ----------
        parent : QWidget | None
            Optional parent widget.

        Returns
        -------
        QWidget
            The tool's main widget to embed in the dock area.
        """

    #: Whether more than one instance of this tool may be open simultaneously.
    allow_multiple_instances: ClassVar[bool] = False
    #: Whether the user can close this tool's dock widget.
    closable: ClassVar[bool] = True

    #: Numerical instance identifier assigned by MainWindow after construction.
    #: ``0`` for single-instance tools; ``1``, ``2``, … for multi-instance tools.
    _instance_id: int = 0

    def _assign_instance_id(self, instance_id: int) -> None:
        """Store the numerical instance identifier.

        Called by :class:`~app.shell.main_window.MainWindow` immediately after
        the tool is constructed and before :meth:`create_widget` is called.
        Override to react to the id (e.g. set up a per-instance logger).

        Parameters
        ----------
        instance_id : int
            ``0`` for single-instance tools; positive integer otherwise.
        """
        self._instance_id = instance_id

    def on_activate(self) -> None:
        """Notify the tool that its dock widget has gained focus."""

    def on_deactivate(self) -> None:
        """Notify the tool that its dock widget has lost focus."""

    def can_close(self) -> bool:
        """Return ``True`` if the tool may be closed right now.

        Called by the shell before closing the tool's dock widget (user-initiated
        close) and before closing the whole application.  Override to show a
        confirmation dialog when there is unsaved / unconfirmed work.

        The default implementation always returns ``True``.
        """
        return True

    def on_close(self) -> None:
        """Notify the tool that its dock widget is about to close."""

    def accepts_path(self, path: Path) -> bool:
        """Return ``True`` if this tool can open *path*.

        Override in tools that support being opened from external sources
        (e.g. via the File Explorer context menu).

        Parameters
        ----------
        path : Path
            A file or directory path to test.

        Returns
        -------
        bool
            Derived from :attr:`handled_path_extensions` and
            :attr:`handles_folders` by default; concrete tools may override.
        """
        if path.is_dir():
            return self.handles_folders
        return path.suffix.lower() in self.handled_path_extensions

    def open_from_path(self, path: Path) -> None:
        """Load *path* into this tool.

        Called after :meth:`accepts_path` returns ``True``.  Override in
        tools that support external path opening.

        Parameters
        ----------
        path : Path
            The file or directory to open.
        """

    def get_metadata(self) -> dict[str, str]:
        """Return tool metadata as a plain dictionary.

        Returns
        -------
        dict[str, str]
            Keys: ``name``, ``category``, ``description``, ``version``.
        """
        return {
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "version": self.version,
        }
