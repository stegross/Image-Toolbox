"""Abstract base classes for all tool plugins."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from typing import ClassVar

from PySide6.QtWidgets import QWidget


class IToolPlugin(ABC):
    """Abstract interface that every tool plugin must implement.

    All tools — both base tools and extension tools — must subclass this
    class and provide the required class attributes and the
    :meth:`create_widget` method.

    Attributes
    ----------
    name : str
        Unique tool name used as the registry key and dock widget title.
    category : str
        Navigation bar category this tool belongs to (e.g. ``"Base"``).
    description : str
        Short human-readable description shown in the UI.
    icon_path : str
        Path to the tool icon relative to the project root.
        Use an empty string if no icon is available.
    version : str
        Tool version string (e.g. ``"1.0.0"``).
    """

    name: ClassVar[str]
    category: ClassVar[str]
    description: ClassVar[str]
    icon_path: ClassVar[str]
    version: ClassVar[str]

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

    def on_activate(self) -> None:
        """Notify the tool that its dock widget has gained focus."""

    def on_deactivate(self) -> None:
        """Notify the tool that its dock widget has lost focus."""

    def on_close(self) -> None:
        """Notify the tool that its dock widget is about to close."""

    def get_metadata(self) -> dict[str, str]:
        """Return tool metadata as a plain dictionary.

        Returns
        -------
        dict[str, str]
            Keys: ``name``, ``category``, ``description``, ``version``.
        """
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "version": self.version,
        }


class IBaseToolPlugin(IToolPlugin, ABC):
    """Abstract base class for base (always-open, non-closable) tools.

    Extends :class:`IToolPlugin` with defaults appropriate for base tools.
    Base tools open automatically on startup, allow multiple instances, and
    cannot be closed by the user.

    Attributes
    ----------
    auto_open_on_startup : bool
        If ``True``, the tool is opened automatically when the application
        starts. Default: ``True``.
    allow_multiple_instances : bool
        If ``True``, more than one instance of this tool may be opened at
        the same time. Default: ``True``.
    closable : bool
        If ``False``, the user cannot close this tool's dock widget.
        Default: ``False``.
    category : str
        Navigation category. Default: ``"Application"``.
    """

    auto_open_on_startup: ClassVar[bool] = True
    allow_multiple_instances: ClassVar[bool] = True
    closable: ClassVar[bool] = False
    category: ClassVar[str] = "Application"
