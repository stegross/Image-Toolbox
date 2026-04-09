# SCIBIT — Tool Specification

> **How to use this document**
> This file describes the current SCIBIT tool in full detail.
> Edit any section to change requirements, then hand it back for implementation.
> Sections marked `[KEEP]` are things that worked well and should be carried over.
> Sections marked `[CHANGE]` are known candidates for improvement.
> Sections with no marker are neutral — edit freely.

---

## 1. Purpose

SCIBIT (Single Chip Image Batch Identification Tool) is a desktop tool for processing a folder of chip images.
For each image it locates the identifier text printed on the chip, reads it via OCR, and renames the file using that text as a prefix.
Images where OCR confidence is too low are flagged for manual review instead of being renamed automatically.

---

## 2. High-Level Phases

The tool operates in three sequential phases:

```
[Configuration] → [Calibration] → [Batch Processing + Result Review]
```

**Configuration** — the user selects a folder, picks a pipeline, picks OCR/CV frameworks, and sets thresholds.
**Calibration** — the user works through a step-by-step wizard on one or more reference images to teach the pipeline where the identifier is located.
**Batch Processing** — the pipeline processes all images in the background; results appear incrementally; the user can review failed items while processing continues.

The user can stop at any point and restart. Stopping after calibration discards calibration data; the next start begins calibration again from scratch.

---

## 3. Configuration Panel

### 3.1 Folder Selection

- The user selects a folder via a file-picker dialog or types a path directly into a line edit.
- Supported image extensions: `.jpg`, `.jpeg`, `.png`.
- The tool scans the folder (non-recursive) and collects all matching files, sorted alphabetically.
- The Start button is disabled until at least one image is found.
- **The selected folder is never restored automatically on next launch.** The user must always choose it explicitly.
- The file dialog opens at the last directory the user navigated to (persisted across launches for convenience), but does not pre-select any folder.

### 3.2 Named Configuration Files

All pipeline settings are stored in named configuration files (see §3.5 for the file format).

#### Config combobox

A combobox at the top of the settings area lists all config files found in the SCIBIT config folder (§3.5).
The first entry is always a hard-coded **"Default"** item, visually distinguished (e.g., greyed-out or italic).
It cannot be overwritten or deleted.
It represents the built-in fallback state and is always available regardless of what files exist on disk.

Below the Default entry, all user-saved config files are listed alphabetically by filename (without extension).

#### Selecting a config

When the user changes the combobox selection, a confirmation dialog appears:

> **"Load configuration?"**
> *"Any unsaved changes to the current settings will be lost. Continue?"*
> [ Load ] [ Cancel ]

If the user cancels, the combobox reverts to the previously selected entry.
If the user confirms, all settings are immediately populated from the chosen config file (or from the hard-coded defaults if "Default" was selected).

#### Save button

A **Save** button sits next to the combobox.
Clicking it opens a file-save dialog filtered to the SCIBIT config file extension, pre-set to the SCIBIT config folder.
If the user navigates to an existing file and confirms, that file is overwritten.
If the user types a new filename, a new config file is created.
After a successful save, the combobox refreshes its list and selects the newly saved file.
Config files can only be deleted outside the tool (via the file manager or OS tools).

### 3.3 Settings

The settings panel is populated from the selected config file (or defaults if "Default" is selected).
The specific fields a config file contains are defined in §3.5.

> **Note:** The exact list of settings and their default values is defined separately in §3.5.
> This section will be filled in once the config file format is agreed (see open items).

### 3.4 Config Group Toggle `[KEEP]`

The settings area is wrapped in a collapsible group box.
When collapsed, only the folder picker, the config combobox + Save button, and the Start button remain visible, giving more vertical space to the active phase.

### 3.5 Config File Format and Location `[TO BE DEFINED]`

**Location:** A dedicated sub-folder inside the SCIBIT application settings directory (e.g., `<app_settings>/scibit/configs/`).
The tool scans this folder on startup and whenever the Save button creates a new file.

**File format and content:** To be defined.
The exact fields that belong in a saved config (which settings are "static" vs. runtime-only) are an open item — the user will specify these.

**Persistent app state** (separate from config files, stored in the main app config):
- Last directory used in the folder file dialog.
- Filename of the last selected config (to restore the combobox selection on next launch, without restoring the folder itself).

---

## 4. CV / OCR Frameworks `[CHANGE — see notes]`

### 4.1 Current design

Two roles exist: **detection** (find text bounding boxes) and **recognition** (read text from a crop).
Each role is filled by exactly one framework instance, selected from a shared dropdown list.
If the same framework name is selected for both roles, a single engine instance is shared.
Engines implement a common interface with two methods: `detect_text_regions(image)` and `recognize_text(image)`.

Available frameworks (both roles):
- **Tesseract** — always available, no extra install.
- **EasyOCR** — requires the `easyocr` package.
- **PaddleOCR** — requires the `paddlepaddle` and `paddleocr` packages.

### 4.2 Notes / known issues

- Both dropdowns show the same list even though not all frameworks perform well in both roles.
- There is no validation that the selected framework is actually installed until the user presses Start, at which point an error dialog appears.
- The distinction between "detection engine" and "recognition engine" is pipeline-specific: Pipeline 1 uses detection to find text regions inside the chip, then recognition on the selected crop. Pipeline 2 uses detection to snap the ROI, then recognition on the snapped crop. A pipeline that only does direct OCR would not need a detection engine at all.

---

## 5. Pipelines

A pipeline encapsulates one complete identification algorithm.
It is responsible for both calibration and batch processing.
The tool ships two pipelines; adding a third requires only: writing the new pipeline file, adding an entry to the pipeline dropdown, and adding a branch in the tool's start logic.

### 5.1 Pipeline 1 — Chip Shape Recognition

**Concept:** The chip boundary is detected automatically by image thresholding. The identifier region is expressed as normalised coordinates within the chip bounding box. During batch processing, the same normalised coordinates are applied to each image's chip bounding box.

**Assumptions:** All chips in the batch have the same shape and roughly the same aspect ratio. The identifier is always in the same relative position within the chip outline.

**Calibration steps (5 steps):**

1. **Chip detection (automatic)** — OpenCV thresholds the reference image and finds contours. The largest contour not touching the image border is taken as the chip outline. Its bounding rectangle is highlighted in green.
2. **Confirm chip boundary** — The user confirms the detected rectangle, requests a retry, or draws the boundary manually with a rubber-band selection.
3. **Text region detection (automatic)** — The detection engine scans inside the chip crop and returns bounding boxes for all text regions. These are shown as pink/magenta rectangles on the image.
4. **Select identifier region** — The user either clicks one of the detected text-region rectangles, or draws a rectangle manually.
5. **OCR confirmation** — OCR is run on the selected region and the recognised text is shown in an editable field. The user corrects it if needed and confirms.

**Calibration output:** chip bounding box (absolute pixels), identifier bounding box as normalised fractions of the chip box, chip aspect ratio, confirmed reference identifier string.

**Batch processing:** For each image, apply the normalised identifier coordinates to the image's chip bounding box (assumed same position and aspect ratio), crop that region, run recognition OCR, compare confidence to threshold.

**Required dependencies:** OpenCV (`cv2`) for chip detection.

---

### 5.2 Pipeline 2 — Direct ROI Selection with Tolerance Correction

**Concept:** The user manually draws a rectangle over the identifier on the reference image. A text-detection pass snaps this rectangle to the nearest detected text region. During batch processing, a tolerance-expanded version of the rectangle (scaled to each image's resolution) is searched for text.

**Assumptions:** The identifier is always roughly in the same position across all images (absolute coordinates, scaled by resolution). Images may vary slightly in size.

**Calibration steps (4 steps):**

1. **Draw ROI** — The image is shown with crosshair cursor. The user draws a rectangle around the identifier.
2. **Snap to text (automatic)** — The detection engine scans inside the drawn ROI and snaps to the nearest detected text region. The snapped rectangle is shown in green.
3. **Confirm snapped region** — The user confirms the snapped rectangle or redraws from scratch.
4. **OCR confirmation** — OCR is run on the snapped region and the user confirms the text.

**Calibration output:** snapped ROI bounding box (absolute pixels in reference image), reference image resolution (width × height), confirmed reference identifier string.

**Batch processing:** For each image, scale the ROI to the image's resolution, expand it by a 40% tolerance margin, run text detection inside the expanded area, pick the detected region closest to the expected centre, crop it, run recognition OCR, compare confidence to threshold.

**Required dependencies:** None beyond the chosen CV/OCR framework.

---

## 6. Calibration UI `[KEEP — architecture]`

### 6.1 Dumb surface principle

The calibration widget is a **dumb surface** — it has no knowledge of which pipeline is active.
It exposes a fixed API (load image, set step label, set buttons, show/hide overlays, start/stop ROI selection, show OCR panel) and a fixed set of signals (ROI drawn, OCR confirmed, scene selection changed).
All step logic lives in a **CalibrationController** class that ships with each pipeline.

### 6.2 CalibrationController

Each pipeline defines a controller that:
- Receives a reference to the calibration widget.
- Connects to the pipeline's signals and the widget's signals.
- Drives the wizard flow by calling the widget's API methods.
- Emits `calibration_complete(CalibrationData)` or `calibration_cancelled` when done.

The controller is instantiated by the pipeline itself via `pipeline.create_calibration_controller()`.
The calibration widget stores the controller as an instance variable (not a local) to prevent garbage collection.

### 6.3 Calibration widget layout (top to bottom)

1. **Step indicator** — "Step N/M: description text"
2. **Image area** — pan/zoom view with optional overlay rectangles; supports rubber-band ROI selection
3. **OCR confirmation panel** — hidden by default; shows a text field and Confirm button when OCR result is ready
4. **Button bar** — dynamically populated by the controller for each step (e.g., Confirm / Retry / Draw Manually / Cancel)

### 6.4 Multi-image calibration

The calibration widget receives the full list of images, not just the first one.
If calibration fails on the first image (e.g., chip not detected), the user can skip to the next image.
A "Skip Image" button appears when more images are available.

### 6.5 ROI selection mode

ROI selection is identified by a string **mode** tag (e.g., `"chip"`, `"identifier"`, `"roi"`).
The mode is passed through the rubber-band and included in the `roi_drawn(mode, rect)` signal so the controller can distinguish multiple possible ROI draws without extra state.

---

## 7. Batch Processing

### 7.1 Threading model `[KEEP]`

All images in the batch are processed **sequentially on a single background thread** (a `QRunnable` submitted to `QThreadPool`).
This avoids thread-safety issues with OCR engines that are not safe to call concurrently.
After each image the worker emits a signal; Qt delivers it to the main thread via its event loop.

### 7.2 Signals emitted during batch

| Signal | Payload | When |
|---|---|---|
| `image_processed` | `PipelineResult` | After each image finishes |
| `progress_updated` | `(current: int, total: int)` | After each image finishes |
| `batch_complete` | — | After the last image |
| `batch_error` | `message: str` | On unrecoverable error |

### 7.3 Result statuses

| Status | Meaning | UI colour |
|---|---|---|
| `ACCEPTED` | Confidence ≥ threshold; file was renamed automatically | Green |
| `PENDING` | Confidence ≥ threshold; rename-preview mode is on; awaiting manual confirmation | Yellow |
| `FAILED` | Confidence < threshold or no text found; needs manual review | Red |
| `MANUAL` | User manually confirmed and renamed via the review panel | Blue |

### 7.4 File renaming

Renamed files use the pattern `{identifier}_{original_filename}`.
If a file with that name already exists, a numeric counter is appended: `{identifier}_{counter}_{original_filename}`.
Rename failures (OS errors) cause the result to fall back to `FAILED`.

---

## 8. Results and Review UI `[KEEP — architecture]`

### 8.1 Layout

The results view is a horizontal splitter:
- **Left pane** — scrollable list of all processed images, added incrementally as results arrive. Each row shows: filename, OCR text, confidence percentage, and a background colour indicating status.
- **Right pane** — review panel (hidden until the user opens a result for review).

A **progress bar** sits above the list and is hidden once the batch completes.
A **summary line** shows counts: Total / Accepted / Pending / Manual / Failed, updated after each image.

### 8.2 Incremental population `[KEEP]`

Results appear in the list one by one as each image finishes, without waiting for the batch to complete.
The user can open the review panel and rename results while the background worker is still processing later images.

### 8.3 Review panel

Opened by double-clicking any non-accepted result.
Shows:
- Full image in a pan/zoom viewer.
- Info line: filename | OCR text | confidence.
- Editable identifier text field (pre-filled with OCR result).
- Prev / Next navigation buttons (keyboard: Left / Right arrow) to move through all failed/pending results.
- Skip button — closes this result without renaming.
- Rename button — renames the file and marks the result as MANUAL.

After every rename the review panel automatically advances to the next pending/failed result.
When no results remain to review, the review panel hides.

---

## 9. Data Models

### 9.1 CalibrationData

Base class with one shared field: `reference_identifier: str` (the confirmed OCR text from calibration).
Each pipeline defines a subclass with its own additional fields:

- `Pipeline1CalibrationData` adds: `chip_bbox`, `identifier_bbox_norm`, `chip_aspect_ratio`
- `Pipeline2CalibrationData` adds: `roi_bbox`, `reference_resolution`

### 9.2 PipelineResult

Represents the outcome for one image:
- `original_path: Path`
- `recognized_text: str | None`
- `confidence: float`
- `status: ResultStatus`
- `new_path: Path | None` (set after a successful rename)

### 9.3 BoundingBox

Axis-aligned rectangle with `(x, y, width, height)` as floats.
Used in both absolute pixel coordinates and normalised (0–1) coordinates depending on context.
Converts to/from `QRectF`.

---

## 10. Plugin Integration

SCIBIT is a plugin that implements `IBaseToolPlugin`.
Key plugin metadata:
- Category: Identification
- Allows multiple instances: No
- Handles folders: Yes (dropped or opened folders load automatically)
- Closable: Yes
- Auto-open on startup: No

Settings are persisted via the application's `ConfigManager` under the tool's name key.
Timing statistics (calibration duration, batch duration, per-image average) are logged at INFO level after batch completion.

---

## 11. Things That Worked Well (do not change without reason)

- **Dumb calibration surface + per-pipeline controller** — adding a pipeline requires zero changes to the calibration widget.
- **`create_calibration_controller()` factory on the pipeline** — the tool code never names a concrete controller class.
- **Sequential batch worker** — solves OCR thread-safety cleanly without locks.
- **Incremental result delivery via signals** — enables reviewing while processing.
- **`CalibrationData` subclass hierarchy** — no union fields; each pipeline's batch worker is typed to its own data class.
- **ROI mode string in `roi_drawn` signal** — controller can distinguish multiple ROI draws without extra boolean flags.

---

## 12. Known Weaknesses in Current Implementation

- `WorkerSignals` (the internal worker signal bus) contains pipeline-1-specific signal names (`chip_result`, `chip_failed`) even though it is shared with pipeline 2. Pipeline 2 simply ignores those signals, but the naming is misleading.
- The status-assignment logic at the end of batch processing (accepted / pending / failed / rename) is duplicated between pipeline 1 and pipeline 2's batch workers.
- `_batch_done` / `_batch_total` tracking and the `_on_batch_image_result` handler are identical in both pipelines and could live in the base class.
- `assert isinstance(calib, Pipeline1CalibrationData)` in `start_batch` — `assert` is disabled in optimised Python runs; should be a proper `TypeError`.
- No validation that selected OCR frameworks are installed until the user presses Start.
- Both detection and recognition dropdowns show the same list of frameworks, with no indication of which frameworks are suitable for which role.
