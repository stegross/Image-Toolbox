"""Wrapper around Qt Advanced Docking System (REQ-HS-001)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QWidget
from PySide6QtAds import CDockManager, CDockWidget, DockWidgetArea

_logger = logging.getLogger("vi_toolbox.shell.docking_manager")


class DockingManager:
    """Manages docked tool widgets using Qt Advanced Docking System.

    Wraps an existing :class:`CDockManager` instance (typically created by
    ``Ui_MainWindow.setupUi``) to provide a simplified interface for adding,
    removing, and focusing tool widgets, and for serialising the layout state.

    Parameters
    ----------
    dock_manager : CDockManager
        The ``CDockManager`` instance created by the ``.ui`` file.
    """

    def __init__(self, dock_manager: CDockManager) -> None:
        self._dock_manager = dock_manager
        self._dock_widgets: dict[str, CDockWidget] = {}

    def add_tool_widget(
        self,
        name: str,
        widget: QWidget,
        closable: bool = True,
        on_close: Callable[[], None] | None = None,
    ) -> CDockWidget:
        """Add a tool widget to the central dock area.

        Parameters
        ----------
        name : str
            Unique tool name used as the dock widget title and lookup key.
        widget : QWidget
            The tool's content widget.
        closable : bool
            Whether the user can close this dock widget.
        on_close : Callable[[], None] | None
            Optional callback invoked when the dock widget is closed via the
            Qt ADS UI.  Use this to clean up registry state and call the
            tool's :meth:`~app.plugin.base.IToolPlugin.on_close` hook.

        Returns
        -------
        CDockWidget
            The created dock widget.
        """
        dock = CDockWidget(name)
        dock.setWidget(widget)

        if not closable:
            dock.setFeature(CDockWidget.DockWidgetFeature.DockWidgetClosable, False)

        def _on_dock_closed() -> None:
            self._dock_widgets.pop(name, None)
            if on_close is not None:
                on_close()

        dock.closed.connect(_on_dock_closed)

        self._dock_manager.addDockWidget(DockWidgetArea.CenterDockWidgetArea, dock)
        self._dock_widgets[name] = dock
        _logger.debug("Added dock widget: %s (closable=%s)", name, closable)
        return dock

    def remove_tool_widget(self, name: str) -> None:
        """Remove and destroy a docked tool widget.

        Parameters
        ----------
        name : str
            Tool name.  No-op if not found.
        """
        dock = self._dock_widgets.pop(name, None)
        if dock is not None:
            self._dock_manager.removeDockWidget(dock)
            _logger.debug("Removed dock widget: %s", name)

    def focus_widget(self, name: str) -> None:
        """Bring a docked widget to the foreground.

        Parameters
        ----------
        name : str
            Tool name.  No-op if not found.
        """
        dock = self._dock_widgets.get(name)
        if dock is not None:
            dock.raise_()
            dock.setAsCurrentTab()

    def save_state(self) -> QByteArray:
        """Serialise the current dock layout state.

        Returns
        -------
        QByteArray
            Serialised state suitable for persistence.
        """
        return self._dock_manager.saveState()

    def restore_state(self, state: QByteArray) -> bool:
        """Restore a previously saved dock layout state.

        Parameters
        ----------
        state : QByteArray
            State returned by a previous call to :meth:`save_state`.

        Returns
        -------
        bool
            ``True`` if the restore succeeded.
        """
        return self._dock_manager.restoreState(state)
