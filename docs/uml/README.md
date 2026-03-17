# Host Shell – UML Design Documents

## Context

These diagrams describe the architecture of the **VI-Toolbox Host Shell**, an extensible desktop GUI for visual inspection (VI) postprocessing of semiconductor chip images. The host shell is part of a master's thesis in Computer Engineering.

## Technology Stack (from Requirements)

- **Language:** Python (REQ-EC-001)
- **GUI Framework:** Qt via PySide (REQ-EC-002)
- **Docking Library:** Qt Advanced Docking System (LGPL, REQ-EC-007)
- **OS:** Windows (REQ-EC-004)
- **Build:** nox -s build (REQ-EC-012)
- **Run (dev):** python -m app (REQ-EC-013)
- **Testing:** pytest (REQ-EC-017)
- **Style:** PEP 8 (REQ-EC-005), NumPy docstrings (REQ-EC-006), UML2 (REQ-EC-006)

## Diagrams

| # | File | UML Type | Description |
|---|------|----------|-------------|
| 1 | `01_host_shell_component_diagram.puml` | Component Diagram | Four-layer architecture: Tools → Tool Interface → Shell/UI → Application Core. Shows IToolPlugin / IBaseToolPlugin hierarchy and static Tool Registry. |
| 2 | `02_host_shell_class_diagram.puml` | Class Diagram | Detailed class design: `IToolPlugin` (abstract), `IBaseToolPlugin` (abstract, extends IToolPlugin), `ToolRegistry` (static registration), shell classes, core classes, and all tool stubs. |
| 3 | `03_host_shell_startup_sequence.puml` | Sequence Diagram | Startup flow: logging init → role check → config load → (tools already statically registered) → UI creation → layout restore → auto-open base tools → show. |
| 4 | `04_host_shell_open_tool_sequence.puml` | Sequence Diagram | Runtime flow when a user opens a tool: instance check (respecting allow_multiple_instances) → role permission → widget creation → docking (respecting closable flag) → activation. |
| 5 | `05_host_shell_shutdown_activity.puml` | Activity Diagram | Shutdown flow: notify tools → save configs → persist layout → flush logs → quit. |
| 6 | `06_host_shell_package_diagram.puml` | Package Diagram | Project directory structure: tools split into `base/` and `extensions/`, registry module with static imports, no plugin loader. |

## Key Design Decisions

### 1. Static Tool Registration (no runtime plugin discovery)

All tools are developed internally in the same repository and compiled/built together with the host shell. There is no runtime plugin discovery or dynamic loading. Instead:

- All tool classes are statically imported in `plugin/registry.py`.
- `ToolRegistry.register(ToolClass)` is called for each tool at import time.
- This ensures that linters, type checkers, and the build system catch errors at build time.
- Adding a new tool requires: (a) implementing `IToolPlugin` or `IBaseToolPlugin`, (b) adding one import + register call in the registry module.

### 2. Two-Level Tool Abstraction

```
IToolPlugin (abstract)
├── IBaseToolPlugin (abstract)
│   ├── ImageViewer
│   ├── FileExplorer
│   └── LogViewer
├── IdentificationTool
└── Future Tool N
```

- **IToolPlugin**: Common interface all tools must implement (name, category, create_widget, lifecycle hooks).
- **IBaseToolPlugin**: Extends IToolPlugin with base-tool-specific defaults:
  - `auto_open_on_startup = True` — base tools open automatically when the application starts.
  - `allow_multiple_instances = True` — base tools can be opened multiple times (REQ-HS-002).
  - `closable = False` — base tools cannot be closed by the user by default.
  - `category = "Base"` — grouped under the "Base" category in the navigation bar.

Extension tools (like the Identification Tool) implement `IToolPlugin` directly and define their own category, instance policy, and closable behaviour.

### 3. Docking via Qt Advanced Docking System (ADS)

Chosen over native `QDockWidget` for tab-grouping, split views, and built-in state serialization for layout persistence (REQ-HS-007). LGPL-licensed (REQ-EC-007).

### 4. Role Management

`RoleManager` queries the Windows account at startup (REQ-HS-013). Permissions are checked before tool instantiation.

### 5. Per-Tool Configuration

Each tool manages its own config via `ConfigManager` (REQ-HS-009). No global settings layer.

## Requirements Traceability

| Requirement | Addressed In |
|-------------|-------------|
| REQ-HS-001 (Docking) | Component Diagram, Class Diagram (DockingManager) |
| REQ-HS-002 (Single Instance) | Open Tool Sequence, Class Diagram (IBaseToolPlugin.allow_multiple_instances) |
| REQ-HS-003 (High-DPI) | Implementation detail (Qt AA_EnableHighDpiScaling) |
| REQ-HS-004 (Tab Bar Navigation) | Component Diagram, Class Diagram (NavigationBar) |
| REQ-HS-007 (Layout Persistence) | Startup Sequence, Shutdown Activity, Class Diagram (LayoutPersistence) |
| REQ-HS-009 (Per-Tool Config) | Class Diagram (ConfigManager) |
| REQ-HS-010 (Startup < 1 min) | Startup Sequence (note) |
| REQ-HS-013 (Role Management) | Open Tool Sequence, Class Diagram (RoleManager) |
| REQ-HS-015 (Extensibility) | Component Diagram, Class Diagram (IToolPlugin, ToolRegistry, static registration) |
| REQ-HS-017 (Logging) | Startup Sequence, Component Diagram |
| REQ-HS-018 (Single Executable) | Package Diagram (noxfile.py note) |
| REQ-HS-020 (Name: VI-Toolbox) | All diagram titles |
| REQ-HS-021 (Base Tools) | Component Diagram, Class Diagram (IBaseToolPlugin subclasses), Startup Sequence (auto-open) |

## Rendering

```bash
# Single diagram
plantuml 01_host_shell_component_diagram.puml

# All diagrams as SVG (for thesis)
plantuml -tsvg *.puml

# All diagrams as PNG
plantuml -tpng *.puml
```

Requires PlantUML + Java. VS Code extension: "PlantUML" by jebbs.
