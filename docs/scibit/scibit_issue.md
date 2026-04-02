## SCIBIT — Single Chip Image Batch Identification Tool

### Overview

Implement the **SCIBIT** extension tool (`app/tools/extensions/identification_tool/`). The tool processes a folder of chip images, automatically recognizes the identifier printed on each chip via OCR, and renames the image files accordingly. Low-confidence results are queued for manual review. The tool supports two recognition pipelines — Chip Shape Recognition (Pipeline 1) and ROI Tolerance Correction (Pipeline 2) — as fully specified in `docs/scibit/scibit_pipelines.md`.

This is the primary deliverable of the thesis MVP scope (REQ-T1-xxx, REQ-B-007).

---

### UI Layout

The tool widget is divided into two vertical regions, both always visible:

```
┌─────────────────────────────────────────────────────────┐
│  CONTROL BAR  (always visible, disabled during process) │
│  [Select Folder]  path/to/folder   [▼ Config]  [Start]  │
├─────────────────────────────────────────────────────────┤
│  PROCESS AREA  (initially empty placeholder)            │
│                                                         │
│  • Calibration steps / pipeline interaction             │
│  • Result list                                          │
│  • Image + rename panel (on list item double-click)     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

- The **Control Bar** is always rendered and contains all persistent controls. All controls in it are **disabled** while the recognition process is running.
- The **Process Area** is empty with a placeholder label before any process is started. Its content is replaced dynamically as the tool moves through pipeline phases.
- The tool must have a **`.ui` file** (`tool.ui`) defining the static skeleton (control bar + process area container with placeholder). Dynamic sub-widgets loaded into the process area can be constructed programmatically.

---

### Functional Requirements

#### 1. Folder Selection

- A **"Select Folder"** button opens a native folder picker dialog (`QFileDialog.getExistingDirectory`).
- The selected folder path is displayed in a read-only line edit next to the button.
- The tool integrates with the File Explorer's "Open in…" context menu, following the same pattern as the Image Viewer:
  - Implements `handles_folders = True` and the appropriate `handled_path_extensions`.
  - Implements `accepts_path(path: Path) -> bool` and `open_from_path(path: Path)`.
  - When opened from the File Explorer with a folder, the folder is pre-filled and the tool is ready for configuration without requiring the user to select a folder again.
- Supported image formats: `.jpg`, `.jpeg`, `.png` (greyscale input, up to 20000×20000 px per REQ-T1).

#### 2. Batch Configuration Panel

A collapsible configuration section (e.g., `QGroupBox` or expandable panel) beneath or beside the folder row, containing:

| Setting | Control | Notes |
|---|---|---|
| **Chip / Identifier Type** | `QComboBox` | Populated from identifier config entries (config file, see §Technical Notes) |
| **Recognition Pipeline** | `QComboBox` | "Pipeline 1 — Chip Shape Recognition" / "Pipeline 2 — ROI Tolerance" |
| **Text Detection Framework** | `QComboBox` | e.g., PaddleOCR, EasyOCR — list from config |
| **OCR Recognition Framework** | `QComboBox` | Same options |
| **Minimum Confidence Score** | `QDoubleSpinBox` | Range 0.0–1.0, default 0.75 |
| **Rename Preview** | `QCheckBox` | If checked, show preview of new filenames before applying renames |

All settings are persisted via `ConfigManager` per-tool instance.

#### 3. Start / Stop Process

- A **"Start"** button initiates the recognition pipeline.
- While running, the button changes to **"Stop"** (or a separate Stop button becomes active) and the rest of the control bar is disabled.
- On completion or stop, the control bar is re-enabled.

---

#### 4. Process Area — Pipeline Calibration Phase

When the process starts, the process area is replaced with the calibration UI for the selected pipeline. Both pipelines share the same overall phase structure: **Calibration → Batch Processing → Results**.

**Calibration phase** occupies the process area and guides the user through the first-image reference setup (see `scibit_pipelines.md` §1.1 and §2.1 for exact step sequences). Key UI elements needed:

- A zoomable image view of the first image (reuse / embed the `_PanZoomView` and `_ImageArea` logic from the Image Viewer — see §Abstraction note below).
- Overlay rendering for detected chip boundaries, text regions, and ROI rectangles (drawn on a `QGraphicsScene`).
- Confirm / Reject / Retry buttons contextual to the current calibration step.
- Manual draw mode for chip boundary and ROI (freehand or rectangular rubber-band selection on the graphics view).
- A step indicator showing progress through the calibration sequence.
- The OCR result confirmation dialog can be an inline text field + confirm button within the process area rather than a popup.

**Batch processing phase** runs automatically after calibration. The process area shows:
- A progress bar (`QProgressBar`) with current image count / total.
- A live-updating result list (see §5).

---

#### 5. Results List and Manual Review

The result list is a scrollable list rendered in the process area. It appears during batch processing and remains visible after completion.

- Uses a `QListWidget` or a `QAbstractListModel` / `QListView` pair.
- Each entry shows: thumbnail (small), filename (original → new), and status indicator.
- **Row background color**:
  - **Green** — successfully renamed.
  - **Red** — failed (OCR confidence below threshold, no match found).
  - **Yellow** — manually corrected and renamed during review.
- **Double-clicking a red (failed) entry** expands or opens a side panel within the process area showing:
  - A zoomable view of the image (same `_PanZoomView` component).
  - A zoomed-in inset of the identifier region.
  - A text input field pre-filled with the OCR best guess (if any).
  - **Rename** and **Skip** buttons.
  - Prev / Next navigation arrows to move between other failed entries without closing the panel.
- After the user renames an entry, it turns yellow in the list.
- The list and review panel are laid out side-by-side once the review panel is open (horizontal splitter, `QSplitter`).

---

#### 6. Control Bar Always-On Behavior

- The control bar (folder selection, config panel, Start/Stop) is always rendered regardless of which phase the process area is in.
- During the recognition process all controls in the bar are disabled (`.setEnabled(False)`) except the Stop button.
- The config panel can remain visible (read-only) during processing so the user can see what settings were used.

---

### Technical Notes

#### `.ui` File

Create `app/tools/extensions/identification_tool/tool.ui` defining:
- The outer two-region layout (control bar + process area with a `QFrame` or `QStackedWidget` placeholder).
- All static control bar widgets (folder button, path edit, config group, start button).
- The process area as a bare `QFrame`/`QWidget` container — dynamic content is loaded programmatically into it by replacing / inserting child layouts.

This file must be loadable in Qt Designer without errors. Dynamic process-area sub-widgets can be separate programmatic classes.

#### Image Viewer Abstraction

The Image Viewer (`app/tools/base/image_viewer/viewer.py`) contains reusable components that SCIBIT needs:
- `_PanZoomView` — zoomable/pannable graphics view.
- `_ImageArea` — image display with navigation and HUD.
- `_ImageListPanel` / `_ImageListModel` — scrollable image list.

These are currently private (`_`-prefixed) to the viewer module. As part of this issue, **extract them into a shared internal module** (e.g., `app/tools/_shared/image_widgets.py`) so both the Image Viewer and SCIBIT can import them. The Image Viewer must continue to function identically after this refactor.

#### File / Module Structure

```
app/tools/extensions/identification_tool/
    __init__.py
    tool.py              # IToolPlugin subclass, plugin registration
    tool.ui              # Qt Designer file for static layout skeleton
    config.py            # Identifier type configs, OCR framework registry
    pipeline/
        __init__.py
        base.py          # Abstract pipeline base class
        pipeline1.py     # Chip Shape Recognition pipeline
        pipeline2.py     # ROI Tolerance Correction pipeline
    ocr/
        __init__.py
        base.py          # Abstract OCR/detection wrapper
        paddle.py        # PaddleOCR implementation (or stub)
    ui/
        __init__.py
        calibration.py   # Calibration phase widget
        results.py       # Results list + manual review widget
```

#### Plugin Registration

Register the tool in `app/plugin/registry.py` following the existing pattern (static import + `ToolRegistry.register(SciBitTool)`). Use `category = ToolCategory.EXTENSION`, `allow_multiple_instances = True`, `closable = True`, `auto_open_on_startup = False`.

#### Config File

Identifier type configurations (regex pattern, polarity, expected character classes) should be stored in a user-editable JSON or TOML file under the app config directory. `ConfigManager` provides the path. The combobox in the UI is populated from this file at tool startup.

---

### Acceptance Criteria

- [ ] Tool appears in the File Explorer "Open in…" context menu for folders and is pre-loaded with the selected folder.
- [ ] All control bar widgets are present and persist their values across sessions via `ConfigManager`.
- [ ] `tool.ui` opens cleanly in Qt Designer.
- [ ] Shared image widgets are extracted to `app/tools/_shared/` without breaking the Image Viewer.
- [ ] Pipeline 1 calibration (chip detection, text region selection, OCR confirmation) flows correctly through all steps on a representative test image.
- [ ] Pipeline 2 calibration (ROI draw, text snap, OCR confirmation) flows correctly.
- [ ] Batch processing runs for all images in the folder; accepted results are renamed; failed results are queued.
- [ ] Result list shows correct colors (green/red/yellow) and double-click opens the review panel.
- [ ] Manual correction renames the file and updates the list entry to yellow.
- [ ] Control bar is disabled during processing and re-enabled on completion or stop.
- [ ] Unit tests cover: pipeline step sequencing, result classification, rename logic (including duplicate suffix handling), and config serialization.

---

### References

- Pipeline specification: `docs/scibit/scibit_pipelines.md`
- Requirements: `docs/requirements_specification.csv` (REQ-T1-xxx)
- Architecture: `docs/uml/README.md`
- Image Viewer (pattern reference): `app/tools/base/image_viewer/viewer.py`
