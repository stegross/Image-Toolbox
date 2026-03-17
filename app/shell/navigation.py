"""Top-level navigation bar with category tabs (REQ-HS-004)."""

from __future__ import annotations

import logging

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


class NavigationBar(QWidget):
    """Horizontal tab bar for navigating and opening tools (REQ-HS-004).

    Reads registered tool categories from :class:`~app.plugin.registry.ToolRegistry`
    and creates one tab per category.  Each tab contains a row of
    :class:`QPushButton` widgets — one per tool in that category.

    When the user clicks a button the :attr:`tool_selected` signal is
    emitted with the tool's name so that
    :class:`~app.shell.main_window.MainWindow` can open it.

    Parameters
    ----------
    tool_registry : ToolRegistry
        Registry instance to read categories and tools from.
    parent : QWidget | None
        Optional parent widget.
    """

    tool_selected: Signal = Signal(str)

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
        """Rebuild the tab bar from the current registry state.

        Clears all existing tabs and recreates them.  Call this again
        after registering new tools if the application is already running.
        """
        self._tab_widget.clear()
        for category in self._tool_registry.get_all_categories():
            tab = self._create_category_tab(category)
            self._tab_widget.addTab(tab, category)
        _logger.debug("Navigation built: %d categories", self._tab_widget.count())

    def on_tool_selected(self, name: str) -> None:
        """Slot called when a tool button is clicked.

        Emits :attr:`tool_selected` with *name*.

        Parameters
        ----------
        name : str
            Tool name as registered in :class:`~app.plugin.registry.ToolRegistry`.
        """
        _logger.debug("Tool selected: %s", name)
        self.tool_selected.emit(name)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_category_tab(self, category: str) -> QWidget:
        """Create the widget for a single category tab.

        Parameters
        ----------
        category : str
            Category name.

        Returns
        -------
        QWidget
            A widget containing one button per tool in *category*.
        """
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)

        for tool_cls in self._tool_registry.get_tools_by_category(category):
            btn = QPushButton(tool_cls.name)
            btn.setToolTip(tool_cls.description)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            # Capture the tool name in the lambda via default argument.
            btn.clicked.connect(lambda _checked=False, n=tool_cls.name: self.on_tool_selected(n))
            row.addWidget(btn)

        row.addStretch()
        return container
