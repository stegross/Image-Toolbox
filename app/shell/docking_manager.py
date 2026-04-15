"""Wrapper around Qt Advanced Docking System (REQ-HS-001)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

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
        can_close: Callable[[], bool] | None = None,
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
        can_close : Callable[[], bool] | None
            Optional guard called when the user requests to close this dock.
            If it returns ``False`` the close is cancelled.  Falls back to
            simple close-signal handling when ``CustomCloseHandling`` is not
            available in the installed Qt ADS version.

        Returns
        -------
        CDockWidget
            The created dock widget.
        """
        dock = CDockWidget(name)
        dock.setWidget(widget)

        if not closable:
            dock.setFeature(CDockWidget.DockWidgetFeature.DockWidgetClosable, False)
        elif can_close is not None:
            try:
                dock.setFeature(CDockWidget.DockWidgetFeature.CustomCloseHandling, True)

                def _on_close_requested() -> None:
                    if can_close():
                        dock.closeDockWidget()

                dock.closeRequested.connect(_on_close_requested)
            except AttributeError:
                _logger.debug("CustomCloseHandling not available — falling back to closed signal")

        def _on_dock_closed() -> None:
            self._dock_widgets.pop(name, None)
            if on_close is not None:
                on_close()

        dock.closed.connect(_on_dock_closed)

        self._dock_manager.addDockWidget(DockWidgetArea.CenterDockWidgetArea, dock)
        self._dock_widgets[name] = dock
        _logger.debug("Added dock widget: %s (closable=%s)", name, closable)
        return dock

    def get_all_widgets(self) -> list[QWidget]:
        """Return the embedded content widget of every currently open dock."""
        widgets = []
        for dock in self._dock_widgets.values():
            w = dock.widget()
            if w is not None:
                widgets.append(w)
        return widgets

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
        result = self._dock_manager.restoreState(state)
        # Qt ADS can restore dock widgets in a closed/hidden state (e.g. when
        # they were a non-active tab).  Force all session-tracked widgets visible.
        for dock in self._dock_widgets.values():
            if dock.isClosed():
                dock.toggleView(True)
        return result
