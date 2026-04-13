"""Central tool registry with static registration at import time.

All tool classes are imported and registered here once — there is no
runtime plugin discovery.  To add a new tool:

1. Implement :class:`~app.plugin.base.IToolPlugin`.
2. Add an import statement in the *Static registrations* section below.
3. Call ``ToolRegistry.register(YourToolClass)``.
   Pass ``auto_open=True`` if the tool should open on first startup / when
   no saved session exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.plugin.categories import ToolCategory
from app.tools.base.file_explorer.explorer import FileExplorer
from app.tools.base.image_viewer.viewer import ImageViewer
from app.tools.base.log_viewer.viewer import LogViewer
from app.tools.extensions.identification_tool.tool import SciBitTool

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from app.plugin.base import IToolPlugin


class ToolRegistry:
    """Registry for all tool plugin classes.

    Uses class-level state so every instance shares the same registry.
    Tools are registered at module import time via :meth:`register`.

    Examples
    --------
    Register a tool at module level::

        ToolRegistry.register(MyTool)

    Query the registry at runtime::

        registry = ToolRegistry()
        tools = registry.get_tools_by_category("Inspection")
    """

    _registered_tools: dict[str, type[IToolPlugin]] = {}
    _instances: dict[str, QWidget] = {}
    # Monotonically increasing per-tool-name counter.  Never reset on close so
    # IDs remain unique for the lifetime of the process.
    _instance_counters: dict[str, int] = {}
    # Tool names that should open automatically on first startup / no saved session.
    _auto_open_tools: set[str] = set()

    @classmethod
    def allocate_instance_key(cls, name: str, allow_multiple: bool) -> tuple[str, int]:
        """Return ``(instance_key, instance_id)`` for a new tool instance.

        For single-instance tools the key equals *name* and the id is ``0``.
        For multi-instance tools the counter for *name* is incremented and the
        key becomes ``"<name> (<id>)"``.

        Parameters
        ----------
        name : str
            Registered tool name.
        allow_multiple : bool
            Whether this tool allows more than one open instance.

        Returns
        -------
        tuple[str, int]
            ``(instance_key, instance_id)``
        """
        if not allow_multiple:
            return name, 0
        new_id = cls._instance_counters.get(name, 0) + 1
        cls._instance_counters[name] = new_id
        return f"{name} ({new_id})", new_id

    @classmethod
    def register(cls, plugin_cls: type[IToolPlugin], *, auto_open: bool = False) -> None:
        """Register a tool plugin class.

        Parameters
        ----------
        plugin_cls : type[IToolPlugin]
            The tool plugin class to register.
        auto_open : bool
            If ``True``, the tool is opened automatically on first startup or
            when no saved session exists.  Default: ``False``.

        Raises
        ------
        ValueError
            If a tool with the same :attr:`~IToolPlugin.name` is already
            registered.
        """
        tool_name = plugin_cls.name
        if tool_name in cls._registered_tools:
            raise ValueError(f"Tool '{tool_name}' is already registered.")
        cls._registered_tools[tool_name] = plugin_cls
        if auto_open:
            cls._auto_open_tools.add(tool_name)

    def get_tool(self, name: str) -> type[IToolPlugin]:
        """Return the registered tool class for *name*.

        Parameters
        ----------
        name : str
            Tool name as defined in :attr:`IToolPlugin.name`.

        Returns
        -------
        type[IToolPlugin]
            The registered tool class.

        Raises
        ------
        KeyError
            If no tool with *name* is registered.
        """
        if name not in self._registered_tools:
            raise KeyError(f"Tool '{name}' is not registered.")
        return self._registered_tools[name]

    def get_tools_by_category(self, category: ToolCategory) -> list[type[IToolPlugin]]:
        """Return all registered tools in *category*.

        Parameters
        ----------
        category : ToolCategory
            Category to filter by.

        Returns
        -------
        list[type[IToolPlugin]]
            Tool classes whose :attr:`~IToolPlugin.category` matches.
        """
        return [t for t in self._registered_tools.values() if t.category == category]

    def get_all_categories(self) -> list[ToolCategory]:
        """Return a sorted list of all unique categories.

        Returns
        -------
        list[ToolCategory]
            Unique categories across all registered tools, sorted by value.
        """
        return sorted({t.category for t in self._registered_tools.values()}, key=lambda c: c.value)

    def get_all_tools(self) -> list[type[IToolPlugin]]:
        """Return all registered tool classes.

        Returns
        -------
        list[type[IToolPlugin]]
            Every registered tool class in registration order.
        """
        return list(self._registered_tools.values())

    def get_auto_open_tools(self) -> list[type[IToolPlugin]]:
        """Return all tools registered with ``auto_open=True``.

        Returns
        -------
        list[type[IToolPlugin]]
            Tool classes that should open on first startup / no saved session.
        """
        return [
            t for name, t in self._registered_tools.items()
            if name in self._auto_open_tools
        ]

    def is_instantiated(self, name: str) -> bool:
        """Return whether *name* has an active widget instance.

        Parameters
        ----------
        name : str
            Tool name.

        Returns
        -------
        bool
            ``True`` if a widget instance is currently tracked.
        """
        return name in self._instances

    def set_instance(self, name: str, widget: QWidget) -> None:
        """Record an active tool widget instance.

        Parameters
        ----------
        name : str
            Tool name.
        widget : QWidget
            The active widget to track.
        """
        self._instances[name] = widget

    def remove_instance(self, name: str) -> None:
        """Remove the tracked instance for *name*.

        Parameters
        ----------
        name : str
            Tool name.  No-op if not tracked.
        """
        self._instances.pop(name, None)

    @classmethod
    def _clear(cls) -> None:
        """Reset all registrations and instances.

        .. warning::
            For use in tests only.
        """
        cls._registered_tools.clear()
        cls._instances.clear()
        cls._instance_counters.clear()
        cls._auto_open_tools.clear()


# ---------------------------------------------------------------------------
# Static tool registrations (REQ-HS-015)
# ---------------------------------------------------------------------------

ToolRegistry.register(FileExplorer, auto_open=True)
ToolRegistry.register(ImageViewer)
ToolRegistry.register(LogViewer, auto_open=True)
ToolRegistry.register(SciBitTool)
