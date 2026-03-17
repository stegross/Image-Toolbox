"""Tool category enumeration."""

from __future__ import annotations

from enum import Enum


class ToolCategory(Enum):
    """Navigation menu categories for tool plugins.

    Each member maps a symbolic constant to the display label used in the
    menu bar.  Add a new member here when introducing a new tool category.

    Examples
    --------
    Assign a category to a tool plugin::

        class MyTool(IToolPlugin):
            category = ToolCategory.IDENTIFICATION
            ...

    Build a menu label::

        menu = self.menuBar().addMenu(category.value)
    """

    APPLICATION = "Application"
    IDENTIFICATION = "Identification"
