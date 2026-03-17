"""Top-level navigation bar with fixed category tabs (REQ-HS-004)."""

from __future__ import annotations

import logging
from typing import ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.plugin.registry import ToolRegistry

_logger = logging.getLogger("vi_toolbox.shell.navigation")

# (tab label, registry category or None, [(button label, action key), ...])
_TabDef = tuple[str, str | None, list[tuple[str, str]]]


class NavigationBar(QWidget):
    """Horizontal tab bar for navigating and opening tools (REQ-HS-004).

    Has three fixed tabs — *Application*, *Identification*, and *Help* —
    each populated with tool buttons from the registry and static action
    buttons.  Tool buttons emit :attr:`tool_selected`; static buttons emit
    :attr:`action_triggered`.

    Parameters
    ----------
    tool_registry : ToolRegistry
        Registry instance to read tool categories from.
    parent : QWidget | None
        Optional parent widget.
    """

    tool_selected: Signal = Signal(str)
    """Emitted with the tool name when a tool button is clicked."""

    action_triggered: Signal = Signal(str)
    """Emitted with an action key when a static button is clicked."""

    # Tab definitions: (tab label, registry category, static actions)
    _TABS: ClassVar[list[_TabDef]] = [
        (
            "Application",
            "Application",
            [("Open Log Folder", "open_log_folder")],
        ),
        (
            "Identification",
            "Identification",
            [],
        ),
        (
            "Help",
            None,
            [("About", "about")],
        ),
    ]

    def __init__(self, tool_registry: ToolRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool_registry = tool_registry
        self._tab_widget = QTabWidget(self)
        self._tab_widget.setDocumentMode(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._tab_widget)

        self.build_navigation()

    def build_navigation(self) -> None:
        """Rebuild all tabs from the current registry state.

        Clears existing tabs and recreates them.  Call again after
        registering new tools at runtime.
        """
        self._tab_widget.clear()
        for tab_label, category, static_actions in self._TABS:
            tab = self._create_tab(tab_label, category, static_actions)
            self._tab_widget.addTab(tab, tab_label)
        _logger.debug("Navigation built: %d tabs", self._tab_widget.count())

    def on_tool_selected(self, name: str) -> None:
        """Emit :attr:`tool_selected` for *name*.

        Parameters
        ----------
        name : str
            Tool name as registered in
            :class:`~app.plugin.registry.ToolRegistry`.
        """
        _logger.debug("Tool selected: %s", name)
        self.tool_selected.emit(name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_tab(
        self,
        tab_label: str,
        category: str | None,
        static_actions: list[tuple[str, str]],
    ) -> QWidget:
        """Create the widget for a single tab.

        Parameters
        ----------
        tab_label : str
            Display name of the tab (unused in layout, used for logging).
        category : str | None
            Registry category whose tools become buttons, or ``None``.
        static_actions : list[tuple[str, str]]
            ``(button label, action key)`` pairs for non-tool buttons.

        Returns
        -------
        QWidget
            Container widget with a row of buttons.
        """
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)

        # Tool buttons from registry
        if category is not None:
            for tool_cls in self._tool_registry.get_tools_by_category(category):
                btn = QPushButton(tool_cls.name)
                btn.setToolTip(tool_cls.description)
                btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                btn.clicked.connect(
                    lambda _checked=False, n=tool_cls.name: self.on_tool_selected(n)
                )
                row.addWidget(btn)

        # Static action buttons
        for label, action_key in static_actions:
            btn = QPushButton(label)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _checked=False, k=action_key: self.action_triggered.emit(k))
            row.addWidget(btn)

        row.addStretch()
        _logger.debug("Tab '%s': built with %d items.", tab_label, row.count() - 1)
        return container
