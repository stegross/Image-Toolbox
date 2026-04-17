# Chip Identifier Recognition System — Formal Specification

**Version:** 1.2 (Draft)
**Date:** 2026-04-15

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Key Requirements](#2-key-requirements)
3. [Core Abstractions](#3-core-abstractions)
   - 3.1 [Operation](#31-operation)
   - 3.2 [Operator](#32-operator)
   - 3.3 [OperatorRegistry](#33-operatorregistry)
   - 3.4 [Stage](#34-stage)
   - 3.5 [Pipeline](#35-pipeline)
   - 3.6 [OperatorPool](#36-operatorpool)
   - 3.7 [Configuration](#37-configuration)
   - 3.8 [CalibrationSession](#38-calibrationsession)
   - 3.9 [IdentifierPatternPreset](#39-identifierpatternpreset)
   - 3.10 [UI Architecture](#310-ui-architecture)
4. [Pipeline Variants](#4-pipeline-variants)
   - 4.1 [Pipeline A: Feature-Based Alignment](#41-pipeline-a-feature-based-alignment)
   - 4.2 [Pipeline B: Contour-Based Alignment](#42-pipeline-b-contour-based-alignment)
   - 4.3 [Pipeline C: Direct ROI](#43-pipeline-c-direct-roi)
5. [Configuration Schema](#5-configuration-schema)
6. [Design Decisions & Rationale](#6-design-decisions--rationale)
   - 6.1 [Calibration Is Always Performed](#61-calibration-is-always-performed)
   - 6.2 [Regex — Dual Purpose](#62-regex--dual-purpose)
   - 6.3 [Preprocessing Is Embedded Per-Stage](#63-preprocessing-is-embedded-per-stage)
   - 6.4 [No Implicit Stages](#64-no-implicit-stages)
   - 6.5 [Manual Override Is a UI Concern](#65-manual-override-is-a-ui-concern)
   - 6.6 [Multi-Operation Operators and Instance Sharing](#66-multi-operation-operators-and-instance-sharing)
7. [Design Patterns Summary](#7-design-patterns-summary)
8. [Batch Processing Behavior](#8-batch-processing-behavior)
   - 8.1 [Execution Flow](#81-execution-flow)
   - 8.2 [Processing Outcome](#82-processing-outcome)
   - 8.3 [Review State](#83-review-state)
   - 8.4 [Progress Reporting](#84-progress-reporting)
   - 8.5 [Output Behavior](#85-output-behavior)
   - 8.6 [Timing](#86-timing)
   - 8.7 [Debug Export](#87-debug-export)
9. [Host Shell Integration](#9-host-shell-integration)
10. [Scientific References](#10-scientific-references)
11. [Open Items / Future Considerations](#11-open-items--future-considerations)

---

## 1. Purpose

This system provides a configurable, pipeline-based tool for recognizing identifier strings printed on semiconductor chip images. It operates within an existing PySide6 GUI host shell.

The system processes batches of chip images where all chips in a batch share the same chip type (same physical structure and layout), but each chip carries a unique identifier string. Images may vary in rotation, position offset, lighting conditions, and identifier print quality.

---

## 2. Key Requirements

**Configurability:** The system must be highly configurable. Saved configurations store the pipeline variant, framework selections, all parameter values, and pipeline-level options. Loading a saved configuration pre-fills all settings so that calibration becomes a quick confirmation flow. Calibration is always performed — configurations accelerate it, they do not bypass it.

**Extensibility:** New pipelines, operations, and operators (framework wrappers) must be easy to add without modifying existing code. The architecture follows the Open/Closed Principle.

**OOP Design:** The codebase uses object-oriented programming with established software design patterns throughout.

**Two Usage Modes:** A knowledgeable user performs initial calibration, tweaks parameters, and saves configurations. A less experienced user loads a saved configuration and confirms calibration steps with minimal adjustment. Both follow the same workflow — the difference is in how much they change.

---

## 3. Core Abstractions

### 3.1 Operation

An **Operation** is an abstract capability with a defined interface. It represents the *what* — a type of computer vision or OCR task — independent of any specific framework or pipeline.

Each operation is defined as an abstract base class (ABC) with:

- A typed `__call__` signature defining inputs and outputs.
- A `get_default_parameters() -> dict` class method returning the default parameter schema with names, types, value ranges, and defaults.

Operations are pipeline-agnostic and framework-agnostic.

**Defined operations (initial set, extensible):**

| Operation | Description | Input | Output |
|-----------|-------------|-------|--------|
| `ChipRegionDetection` | Detect the chip boundary within the full image | Image (ndarray) | Bounding box or contour |
| `ContourBasedDetection` | Detect chip boundary via edge/contour analysis | Image (ndarray) | Rotated bounding rectangle + contour |
| `FeatureBasedAlignment` | Align an image to a reference template using keypoint matching | Image + template + keypoints | Homography matrix + warped image |
| `ContourBasedAlignment` | Align/normalize an image using detected contour geometry | Image + rotated rect | Normalized image |
| `TextRegionDetection` | Detect all text regions within an image | Image (ndarray) | List of bounding boxes with confidence |
| `CropPreprocessing` | Preprocess a cropped image region for OCR | Image (ndarray) + params | Preprocessed image (ndarray) |
| `TextRecognition` | Recognize text from a preprocessed crop | Image (ndarray), optional character set hint | String + confidence score |

Note: Additional operations may be defined as new pipelines are added. The operation set is not closed.

### 3.2 Operator

An **Operator** is a framework wrapper that implements one or more operations. It is the *who* — PaddleOCR, OpenCV, EasyOCR, Tesseract, etc. A single operator instance can serve multiple stages in a pipeline, provided those stages require operations that the operator supports.

Each operator:

- Implements one or more operation ABCs (via multiple inheritance or explicit interface implementation).
- Registers itself with the OperatorRegistry at import time, declaring which operations it supports.
- Manages its own model lifecycle internally. Models and resources are lazily initialized — a sub-model is only loaded when an operation that requires it is first called. This avoids loading unnecessary models when only a subset of an operator's capabilities are used.
- Declares its configurable parameters per operation (inheriting defaults from the operation ABCs, potentially adding framework-specific parameters). Parameters are passed per-call from the stage, not stored on the operator instance, so the same operator instance can serve two stages with different parameter values.
- Can accept an optional character set hint (derived from regex) if the operation interface supports it. Operators that do not support it ignore the hint.

**Design pattern:** Strategy — operators are interchangeable implementations behind operation interfaces. The fact that one operator implements multiple operation interfaces does not break the pattern; it remains swappable per-operation.

**Defined operators (initial set, extensible):**

| Operator | Implements | Notes |
|----------|-----------|-------|
| `OpenCVOperator` | `ChipRegionDetection`, `ContourBasedDetection`, `FeatureBasedAlignment`, `ContourBasedAlignment`, `CropPreprocessing` | Covers all non-OCR computer vision tasks. Feature alignment supports both ORB and SIFT via parameter selection. Preprocessing covers CLAHE, adaptive thresholding, morphological operations, and upscaling. |
| `PaddleOCROperator` | `TextRegionDetection`, `TextRecognition` | Lazily initializes detection and recognition sub-models independently. Supports character set hint for constrained recognition. |
| `EasyOCROperator` | `TextRegionDetection`, `TextRecognition` | Lazily initializes detection and recognition capabilities independently. |
| `TesseractOperator` | `TextRecognition` | Supports character whitelist for constrained recognition. Does not support text region detection. |

Note: Additional operators may be added by implementing the relevant operation ABCs and registering with the OperatorRegistry. The `CropPreprocessing` operation may have multiple sub-steps configured within the stage that uses it (see Section 6.3).

### 3.3 OperatorRegistry

A singleton registry that tracks all available operators and the operations each supports.

**Design pattern:** Registry / Plugin.

**Responsibilities:**

- Operators register themselves at import time (via decorator or explicit registration call), declaring which operations they implement.
- Queried by operation: "give me all operators that implement `TextRecognition`" → returns list of operator classes. Used by the GUI to populate dropdown menus per stage.
- Queried for validation: "is this operator assignment valid for this pipeline?" → verifies that every stage has an assigned operator that implements the required operation.
- Supports the OperatorPool (see Section 3.6) by providing class references for instantiation.

### 3.4 Stage

A **Stage** is a named slot in a pipeline's sequence. It is the structural unit of both calibration and batch processing.

Each stage:

- Has a unique name within its pipeline (e.g., `"chip_region_detection"`, `"text_recognition"`).
- Declares which operation it requires.
- References an assigned operator class (set via configuration or user selection). The actual operator instance is obtained from the pipeline's OperatorPool (see Section 3.6) — the stage does not instantiate operators directly.
- Holds the current parameter values for the operation. These parameters are passed to the operator on each call, not stored on the operator instance. This allows two stages that share the same operator instance to use different parameter values.
- Includes preprocessing parameters relevant to this stage's task (preprocessing is embedded per-stage, not a separate stage — see Section 6.3).

**Execution modes:**

- **Calibration mode:** `run_calibration(image, session)` — Obtains the operator from the pool, executes it with current parameters, returns the result for user review. The GUI handles the confirm/adjust/retry/manual-override loop. The stage itself does not contain UI logic.
- **Batch mode:** `run_batch(image, session)` — Obtains the operator from the pool, executes it with fixed parameters, returns the result. No user interaction.

**Manual fallback during calibration:** When the user overrides a stage's result manually (e.g., drawing a bounding box), this is handled by the GUI/calibration controller, not by the stage or operator. The stage receives the manually-provided result and stores it in the CalibrationSession as if the operator produced it. This keeps the operator abstraction clean — there is no "manual operator."

### 3.5 Pipeline

A **Pipeline** is an ordered sequence of stages defining a complete processing approach.

**Design pattern:** Template Method — the pipeline base class defines the mechanics of calibration flow and batch iteration; subclasses define which stages exist and in what order.

The base class provides:

- `get_stages() -> list[Stage]` — abstract, defined by each subclass.
- `run_calibration(image, session)` — iterates through stages in calibration mode.
- `run_batch(images, session, config)` — iterates through all images, running each stage in batch mode. Emits progress signals.
- PySide6 signals for progress reporting (Observer pattern — the GUI connects to these signals).

**Critical rule:** Each pipeline subclass declares its complete stage sequence explicitly, including any stages that happen to be shared across pipelines. There are no implicit/inherited stages from the base class. This ensures transparency — reading a pipeline definition shows the full picture.

### 3.6 OperatorPool

The **OperatorPool** is a pipeline-level cache that manages operator instances. It ensures that when multiple stages are assigned to the same operator class, they share a single instance rather than each creating their own. This avoids redundant model initialization (e.g., PaddleOCR loading its models twice when used for both text detection and text recognition).

**Design pattern:** Object Pool / Flyweight.

**Behavior:**

- Owned by the pipeline instance. Created when the pipeline is constructed, destroyed when the pipeline is torn down.
- Internally maps operator class → live instance (a dict).
- When a stage needs its operator, it requests it from the pool via `get_operator(operator_class) -> operator_instance`. If an instance of that class exists in the pool, it is returned. If not, a new instance is created, added to the pool, and returned.
- Operator instances are stateless with respect to parameters — parameters are passed per-call from the stage. This is what makes sharing safe: two stages with different parameter values can share an operator instance without conflict.

**Lifecycle during calibration:**

When a user changes the operator assignment for a stage during calibration:

1. The stage's assigned operator class is updated.
2. The pool checks whether the new operator class already has a live instance. If so, it is reused. If not, it is instantiated.
3. The pool checks whether the *old* operator class is still referenced by any other stage in the pipeline. If no stage references it, the instance is removed from the pool and its resources are released (models unloaded). If another stage still references it, the instance remains.

This reference-checking ensures unused operators are cleaned up promptly (important for GPU memory with large OCR models), while shared operators stay alive as long as any stage needs them.

### 3.7 Configuration

The system uses a **two-level configuration** approach:

**Session configuration** (single file, managed by host shell's ConfigManager): Persists minimal session state across application launches — the last used folder path and the name of the last selected pipeline configuration. This is not a pipeline configuration; it simply restores the UI to where the user left off.

**Pipeline configuration** (individual JSON files, one per saved config): A serializable data structure that captures all settings needed to pre-fill calibration. Selected via a combo box in the UI.

**Pipeline configuration contents:**

- Pipeline variant identifier (e.g., `"feature_based_alignment"`)
- Per-stage configuration:
  - Assigned operator identifier (e.g., `"PaddleOCROperator"`)
  - All parameter values for the operation in that stage (including embedded preprocessing parameters)
- Pipeline-level options:
  - Identifier pattern preset name (string, references an `IdentifierPatternPreset` — see Section 3.9)
  - Rough rotation angle (float, -180° to +180°, default 0°)
  - Invert colors (boolean, default false — inverts image colors before processing, for bright text on dark backgrounds)
  - Manual confirmation required (boolean)
  - Confidence threshold (float, 0–100%)
  - Debug export mode (enum: `DISABLED` | `CALIBRATION` | `ALL`, default `DISABLED` — see Section 8.7)

**Does NOT contain:**

- Calibration data (template images, keypoints, computed ROI coordinates)
- Image data of any kind
- Batch-specific paths or results

**Design pattern:** Builder or Factory — a pipeline with its operator assignments is constructed from a loaded configuration. During construction, the factory reads the operator assignments per stage, and the OperatorPool handles deduplication of instances automatically.

### 3.8 CalibrationSession

An ephemeral, non-serialized object that holds all data produced during calibration. It exists only for the duration of a batch processing session.

**Design:** The CalibrationSession is abstract. Each pipeline subclass defines its own concrete CalibrationSession subclass containing only the attributes that pipeline needs. This follows the same principle as pipeline stage declarations — each pipeline fully owns its calibration data structure, and adding a new pipeline never requires modifying a shared class.

**Base class attributes (shared by all pipelines):**

- Selected example image (after rough rotation and color inversion applied)
- Rough rotation angle (applied to all batch images before pipeline stages)
- Invert colors flag (applied to all batch images before pipeline stages)

**Concrete subclasses define pipeline-specific attributes, for example:**

- `FeatureAlignmentCalibrationSession`: template image, template keypoints and descriptors, chip region bounding box/contour, identifier region bounding box (in normalized chip coordinates)
- `ContourAlignmentCalibrationSession`: template image, chip region contour and rotated rectangle, identifier region bounding box (in normalized chip coordinates)
- `DirectROICalibrationSession`: identifier region bounding box (in rough-rotated image coordinates), ROI tolerance margin

The CalibrationSession is passed to every stage during batch processing so stages can reference calibration data (e.g., the alignment stage references template keypoints).

### 3.9 IdentifierPatternPreset

An **IdentifierPatternPreset** is a named, reusable definition of an identifier pattern. It bundles a regex pattern with a human-readable name and description, making regex-based validation accessible to non-technical users.

**Fields:**

- `name` (string) — Human-readable label shown in the UI (e.g., "Standard Cxxx-yy").
- `regex` (string) — Regular expression the recognized text must match.
- `description` (string) — Optional tooltip/help text explaining what the pattern matches.

**IdentifierPatternPresetRegistry:**

- Loads presets from a JSON configuration file at startup (read-only — no editing via GUI).
- Always includes a hardcoded default preset: `name="Default (accept any)"`, `regex=".*"`, `description="Accept any OCR output without pattern filtering."` This default is always available even if the config file is missing or empty.
- Provides `get_preset_names() -> list[str]` for populating combo boxes in the UI.
- Provides `get_preset(name) -> IdentifierPatternPreset` for retrieving the selected preset.
- The pipeline configuration references a preset by name. When a configuration is loaded, the preset name is resolved via the registry to obtain the regex.

**Usage in the pipeline:**

- The preset's regex is used for two purposes: final validation (pass/fail in the Validation stage) and deriving a character set hint passed to TextRecognition operators that support constrained recognition.
- When the default `".*"` preset is active, validation always passes and no useful character set hint is derived, so operators run unconstrained.

### 3.10 UI Architecture

The tool's user interface follows a **Passive View** pattern for the calibration and review phases.

**Layout structure:**

- **Control bar** (top, always visible): Folder selection, pipeline configuration selector, Start/Stop button, and a collapsible configuration group box. Disabled during processing, re-enabled after batch completion.
- **Process area** (bottom, dynamic content): Shared region used for both calibration and review. Since calibration is always followed by review (never concurrent), the same area swaps between a calibration view and a results view. Defined in a `.ui` file (Qt Designer compatible).

**Calibration area layout:** Left side is the image preview (updating live as settings change). Right side is the controls panel with stage-specific parameters, action buttons, and overlays. This left-right split applies to all stages.

**CalibrationWidget (passive view):** A UI surface with no logic of its own. Provides a well-defined API that any pipeline's controller can drive:

- `load_image(path)` — display an image in the preview area
- `set_step(current, total, description)` — update the step indicator ("Step 2/5: Confirm chip boundary")
- `set_buttons(specs)` — configure the action button bar
- `start_roi_selection(mode)` / `stop_roi_selection()` — enable/disable drawing regions
- `show_rect_overlay(rect, color, width)` / `clear_overlays()` — draw bounding box overlays on the image
- `show_ocr_panel(text)` / `hide_ocr_panel()` — show/hide the OCR confirmation panel with an editable text field
- `show_error(message)` — display error dialogs

**CalibrationController (abstract, one per pipeline):** Orchestrates the calibration flow by calling CalibrationWidget API methods in response to pipeline signals. Each pipeline subclass ships its own concrete controller. The controller connects pipeline signals (e.g., `chip_detected`, `text_regions_detected`, `ocr_result_ready`) to widget API calls, managing the step-by-step flow. Emits `calibration_complete(CalibrationSession)` when finished.

**ResultsWidget:** Replaces the calibration widget in the process area after calibration completes. Connects to pipeline signals (`image_completed`, `progress_updated`, `batch_completed`) and manages the full review workflow. Contains:

- **Progress bar** (top): Shows batch progress, hidden after completion.
- **Summary label**: Live-updating counts displayed as "Total: X | Accepted: Y | Pending: Z | Manual: W | Failed: F". Updates after each image is processed and after each manual confirmation.
- **Results list** (left side of a horizontal splitter): A `QListWidget` dynamically populated as images are processed. Each item shows the filename, recognized OCR text, and confidence percentage, color-coded by `ReviewState`. The `ResultsWidget` receives `BatchResult` from the pipeline (containing `ProcessingOutcome`) and uses `ReviewStateMapping` to assign the initial `ReviewState` and color. Double-clicking a non-auto-accepted item opens the review panel for that item.
- **Review panel** (right side of the splitter, initially hidden): An internal sub-widget for manual review of individual results. Opens when the user double-clicks a reviewable item.

**Review panel:** Contains the full image preview, an info label (filename, OCR text, confidence), an editable identifier text field, and action buttons (Prev, Skip, Rename/Confirm, Next). The widget maintains a review queue — an ordered list of items needing review with an index pointer. Navigation moves through this queue.

**Review panel workflow:** Optimized for keyboard-driven operation. When a result needing review is loaded, the identifier text field is automatically focused and fully selected so the user can immediately type a correction. The Enter key submits the confirmation, triggers the file copy, updates the item to `MANUALLY_CONFIRMED` (blue) with visual feedback ("filename → new_filename | Manual | ✓"), removes the item from the review queue, and automatically advances to the next item needing review. If the review queue is empty after confirmation, the review panel hides. Left/right arrow keys navigate between review items. Mouse interaction remains available as an alternative.

**Unconfirmed work protection:** The system warns the user before actions that would lose unconfirmed results: opening a new folder, stopping a running batch, or starting a new run. The results widget exposes a `has_unconfirmed` property checked before allowing these actions.

**Design pattern:** Passive View — the CalibrationWidget has no decision-making logic; the CalibrationController holds all flow control. This keeps the widget reusable across all pipeline variants without modification.

---

## 4. Pipeline Variants

Each pipeline defines its own complete stage sequence. The following are the initial pipeline variants. Additional pipelines can be added by subclassing the pipeline base class and defining stages.

### 4.1 Pipeline A: Feature-Based Alignment

**Best for:** Chips with sufficient visual texture and internal features (text, logos, circuit patterns) for reliable keypoint matching.

**Scientific basis:** Feature-based image registration using ORB (Rublee et al., 2011, "ORB: An efficient alternative to SIFT or SURF," IEEE ICCV) or SIFT (Lowe, 2004, "Distinctive image features from scale-invariant keypoints," IJCV 60(2), pp. 91–110) descriptors with RANSAC-based homography estimation (Fischler & Bolles, 1981, "Random sample consensus: A paradigm for model fitting with applications to image analysis and automated cartography," Communications of the ACM 24(6), pp. 381–395). This approach is standard in industrial machine vision for template-based alignment of objects with unknown pose.

**Stages:**

| # | Stage Name | Required Operation | Description |
|---|------------|--------------------|-------------|
| 0 | Calibration Setup | *(built-in, no operation)* | Select example image from batch (skip unsuitable images), adjust rough rotation via slider (-180° to +180°), toggle color inversion. All options presented together on the right panel with live preview on the left. |
| 1 | Chip Region Detection | `ChipRegionDetection` | Detect chip boundary in the full image. User confirms, adjusts parameters, or draws manually. |
| 2 | Feature-Based Alignment | `FeatureBasedAlignment` | Extract keypoints from normalized chip, match against template (stored in CalibrationSession from calibration image). Compute homography, warp to canonical pose. User confirms alignment quality. |
| 3 | Identifier Region Detection | `TextRegionDetection` | Detect text regions in the aligned chip image. User selects which region is the identifier, or draws the ROI manually. |
| 4 | Text Recognition | `TextRecognition` | Preprocess the identifier crop (preprocessing params embedded in this stage), run OCR. User confirms recognized string. Character set hint derived from regex is passed to operator if supported. |
| 5 | Validation | *(built-in, no operation)* | Check recognized string against regex pattern. Report pass/fail. |

**Key parameters exposed:**

- Stage 1: Detection method (threshold-based, edge-based), blur kernel size, min contour area, contrast enhancement strength.
- Stage 2: Feature detector type (ORB/SIFT, as a parameter of the `OpenCVOperator`), match threshold (ratio test), RANSAC reprojection tolerance, minimum match count.
- Stage 3: Text detection confidence threshold, minimum text region area.
- Stage 4: CLAHE clip limit, CLAHE tile size, adaptive threshold block size, adaptive threshold constant, morphological kernel size, morphological operation type, upscale factor, upscale interpolation method.

### 4.2 Pipeline B: Contour-Based Alignment

**Best for:** Chips with clean, well-defined edges on a monotone/uniform background, but potentially few internal visual features.

**Scientific basis:** Contour detection via Canny edge detection (Canny, 1986, "A computational approach to edge detection," IEEE TPAMI 8(6), pp. 679–698) followed by contour extraction and polygon approximation (Suzuki & Abe, 1985, "Topological structural analysis of digitized binary images by border following," CVGIP 30(1), pp. 32–46, as implemented in OpenCV's `findContours`). Geometric normalization via minimum area bounding rectangle (rotating caliper method, Toussaint, 1983, "Solving geometric problems with the rotating calipers," IEEE MELECON). Perspective correction via four-point homography is well-established in document scanning and industrial inspection literature.

**Stages:**

| # | Stage Name | Required Operation | Description |
|---|------------|--------------------|-------------|
| 0 | Calibration Setup | *(built-in)* | Select example image, adjust rough rotation, toggle color inversion. |
| 1 | Contour-Based Chip Detection | `ContourBasedDetection` | Detect chip boundary via edge detection and contour analysis. Returns rotated bounding rectangle. User confirms or adjusts. |
| 2 | Contour-Based Alignment | `ContourBasedAlignment` | Normalize chip geometry using the detected contour/rectangle. Crop and rotate to canonical orientation. User confirms. |
| 3 | Identifier Region Detection | `TextRegionDetection` | Detect text regions, user selects identifier region. |
| 4 | Text Recognition | `TextRecognition` | Preprocess and OCR the identifier crop. |
| 5 | Validation | *(built-in)* | Regex check. |

**Key parameters exposed:**

- Stage 1: Canny low/high thresholds, Gaussian blur kernel size, minimum contour area, contour approximation epsilon, expected aspect ratio range (to filter non-chip contours).
- Stage 2: Padding around detected rectangle, interpolation method for warp.
- Stages 3–5: Same as Pipeline A.

### 4.3 Pipeline C: Direct ROI

**Best for:** Fixed-camera setups where images are already roughly aligned. Skips complex alignment entirely.

**Scientific basis:** Direct region-of-interest extraction is the simplest approach in machine vision when mechanical fixtures or calibrated cameras ensure consistent part placement (standard practice in industrial AOI systems). Minor positional variance is handled by searching within a tolerance margin around the expected ROI.

**Stages:**

| # | Stage Name | Required Operation | Description |
|---|------------|--------------------|-------------|
| 0 | Calibration Setup | *(built-in)* | Select example image, adjust rough rotation, toggle color inversion. |
| 1 | Identifier Region Selection | *(built-in, manual)* | User draws the identifier ROI directly on the (rough-rotated) image. No automatic detection. |
| 2 | Text Recognition | `TextRecognition` | Preprocess and OCR the identifier crop. |
| 3 | Validation | *(built-in)* | Regex check. |

**Key parameters exposed:**

- Stage 1: ROI tolerance margin (pixels) — during batch processing, the system searches within this margin around the calibrated ROI position to handle minor positional variance.
- Stages 2–3: Same as other pipelines.

---

## 5. Configuration Schema

```json
{
  "_comment": "Example saved pipeline configuration",
  "pipeline": "feature_based_alignment",

  "pipeline_options": {
    "identifier_pattern_preset": "Standard Cxxx-yy",
    "rough_rotation_degrees": 180.0,
    "invert_colors": false,
    "manual_confirmation_required": true,
    "confidence_threshold_percent": 85.0,
    "debug_export_mode": "disabled"
  },

  "stages": {
    "chip_region_detection": {
      "operator": "OpenCVOperator",
      "parameters": {
        "blur_kernel_size": 5,
        "contrast_enhancement": 1.5,
        "min_contour_area": 10000
      }
    },

    "feature_based_alignment": {
      "operator": "OpenCVOperator",
      "_comment": "Same operator class as stage above — OperatorPool shares one instance",
      "parameters": {
        "feature_detector_type": "ORB",
        "match_threshold": 0.75,
        "ransac_reproj_threshold": 5.0,
        "min_match_count": 10
      }
    },

    "identifier_region_detection": {
      "operator": "PaddleOCROperator",
      "parameters": {
        "detection_confidence_threshold": 0.5,
        "min_text_region_area": 100
      }
    },

    "text_recognition": {
      "operator": "PaddleOCROperator",
      "_comment": "Same operator class as stage above — OperatorPool shares one instance",
      "parameters": {
        "clahe_clip_limit": 2.0,
        "clahe_tile_size": 8,
        "adaptive_threshold_block_size": 31,
        "adaptive_threshold_constant": 10,
        "morphology_kernel_size": 2,
        "morphology_operation": "close",
        "upscale_factor": 2.0,
        "upscale_interpolation": "cubic",
        "use_character_set_hint": true
      }
    }
  }
}
```

---

## 6. Design Decisions & Rationale

### 6.1 Calibration Is Always Performed

Even with a saved configuration, calibration runs every time. The configuration pre-fills all parameters and operator selections, so for a well-tuned config on a familiar chip type, calibration becomes a quick sequence of confirmations. But it is never skipped because:

- Batch-to-batch variance (different camera, different day, different lighting rig) can invalidate assumptions.
- The CalibrationSession (template image, keypoints, ROI) must be freshly computed from the current batch's example image.
- Requiring confirmation ensures the user catches problems before processing hundreds or thousands of images.

### 6.2 Regex — Dual Purpose

The identifier regex pattern is obtained from the `IdentifierPatternPreset` referenced in the pipeline-level configuration (see Section 3.9) and serves two roles:

1. **Pipeline-level validation (Stage: Validation):** After text recognition, the final string is matched against the preset's regex. Non-matching results are flagged with `VALIDATION_FAILED` status. Validation is always active — the default preset uses `".*"` which matches any string, so when no specific pattern is configured, all results pass validation. This ensures every result always carries a regex pass/fail status regardless of configuration.
2. **Operator hint (within TextRecognition):** A character set is derived from the regex (e.g., `^[A-Z]{2}\d{6}$` → allowed chars: `A-Z`, `0-9`) and passed to the TextRecognition operator. Operators that support constrained recognition (PaddleOCR, Tesseract) use this to bias predictions. Operators that do not support it ignore the hint. When the default `".*"` pattern is in use, no useful character set can be derived, so operators run unconstrained.

### 6.3 Preprocessing Is Embedded Per-Stage

Preprocessing (image enhancement, filtering, normalization) is not a separate pipeline stage. Instead, each stage that benefits from preprocessing includes the relevant preprocessing parameters in its own configuration. Rationale:

- Different stages need different preprocessing (chip detection benefits from blur and edge enhancement; OCR benefits from CLAHE and thresholding).
- Making preprocessing a separate stage would fragment the calibration flow — the user would confirm preprocessing in isolation without seeing its effect on the downstream task.
- Embedding preprocessing means the user sees and adjusts its effect in context: "did the chip get detected correctly?" rather than "does this blurred image look right?"

### 6.4 No Implicit Stages

Each pipeline subclass declares its complete ordered list of stages, even if some stages (like Calibration Setup, Validation) are conceptually shared across pipelines. This creates minor redundancy in pipeline definitions but ensures transparency: reading a pipeline's stage list shows the full sequence without requiring knowledge of the base class.

### 6.5 Manual Override Is a UI Concern

When a user manually draws a bounding box or corrects a text string during calibration, this is handled by the GUI calibration controller — not by the stage or operator. The stage receives the corrected result and proceeds normally. This keeps the operator abstraction clean and avoids a "ManualOperator" anti-pattern that would mix UI interaction into the framework/operation layer.

### 6.6 Multi-Operation Operators and Instance Sharing

Operators are framework wrappers that may implement multiple operations (e.g., `PaddleOCROperator` implements both `TextRegionDetection` and `TextRecognition`). When two stages in a pipeline are assigned to the same operator class, they share a single instance via the OperatorPool. This avoids redundant model initialization, which is critical for performance — OCR frameworks like PaddleOCR can take significant time and GPU memory to load models.

To make instance sharing safe, operators are stateless with respect to parameters. Parameters are passed to the operator on each call from the stage, not stored on the operator instance. This means two stages that share a `PaddleOCROperator` instance can each use different parameter values without conflict.

Operators lazily initialize their internal sub-models. If only the `TextRegionDetection` capability of `PaddleOCROperator` is used (because a different operator handles recognition), the recognition model is never loaded. This minimizes resource usage when an operator's full capability set is not needed.

The trade-off is explicit: if a user assigns different operators to different stages (e.g., PaddleOCR for detection, EasyOCR for recognition), both frameworks must be initialized, which increases resource usage. This is a conscious configuration choice — the user accepts the overhead in exchange for potentially better results from mixing frameworks.

---

## 7. Design Patterns Summary

| Pattern | Where Used | Purpose |
|---------|-----------|---------|
| **Strategy** | Operators implementing operations | Interchangeable framework implementations behind a common interface. A single operator may implement multiple operation interfaces without breaking the pattern. |
| **Registry / Plugin** | OperatorRegistry | Discovery and extensibility for operators; enables adding new frameworks without modifying existing code. Indexes operators by the operations they support. |
| **Object Pool** | OperatorPool | Manages operator instance lifecycle at the pipeline level. Deduplicates instances when multiple stages share an operator class. Handles cleanup when operator assignments change during calibration. |
| **Template Method** | Pipeline base class | Defines calibration and batch processing flow; subclasses define stage sequences |
| **Factory** | Pipeline construction from configuration | Build a fully configured pipeline from a saved config file. The OperatorPool handles instance deduplication during construction. |
| **Observer** | Pipeline progress signals (PySide6 signals) | Decouple batch processing progress from GUI display logic |
| **Passive View** | CalibrationWidget + CalibrationController | UI surface has no logic; controller drives all calibration flow. Keeps widget reusable across pipeline variants. |

---

## 8. Batch Processing Behavior

### 8.1 Execution Flow

For each image in the batch:

1. Apply rough rotation (from pipeline-level config, confirmed in calibration).
2. Apply color inversion if enabled (from pipeline-level config, confirmed in calibration).
3. Execute each stage in sequence using batch mode, referencing the CalibrationSession for template data, ROI coordinates, etc.
4. Collect result: filename, recognized identifier string, confidence score, processing outcome.
5. Assign `ProcessingOutcome` based on regex validation (from `IdentifierPatternPreset`) and confidence threshold.
6. Emit `BatchResult` containing filename, text, confidence, and `ProcessingOutcome`. The pipeline does not assign `ReviewState` — that is the responsibility of the UI layer (ResultsWidget) using the `ReviewStateMapping`.

### 8.2 Processing Outcome

The pipeline assigns a `ProcessingOutcome` to each image based on confidence threshold and regex validation. This is pure processing logic with no UI concern.

| ProcessingOutcome | Condition |
|-------------------|-----------|
| `PASSED` | Confidence ≥ threshold AND regex matches |
| `LOW_CONFIDENCE` | Confidence < threshold AND regex matches |
| `VALIDATION_FAILED` | Confidence ≥ threshold AND regex does not match |
| `FAILED` | Confidence < threshold AND regex does not match |
| `PROCESSING_ERROR` | A stage threw an exception (alignment failed, no text detected, etc.) |

### 8.3 Review State

The review system maps each `ProcessingOutcome` to a `ReviewState` based on the manual confirmation setting. Each `ReviewState` carries a display color for the results list.

**ReviewState enum:**

| ReviewState | Color | RGB | Meaning |
|-------------|-------|-----|---------|
| `AUTO_ACCEPTED` | Green | (180, 230, 180) | Automatically accepted and renamed, no review needed |
| `PENDING_REVIEW` | Yellow | (255, 235, 150) | Awaiting user review |
| `NEEDS_ATTENTION` | Orange | (255, 200, 130) | Higher severity, awaiting user review |
| `CRITICAL` | Red | (240, 180, 180) | Worst outcome, awaiting user review |
| `MANUALLY_CONFIRMED` | Blue | (160, 200, 240) | User has reviewed and confirmed/edited the result |

**Mapping when manual confirmation = false:**

| ProcessingOutcome | → ReviewState |
|-------------------|---------------|
| `PASSED` | `AUTO_ACCEPTED` (green) |
| `LOW_CONFIDENCE` | `PENDING_REVIEW` (yellow) |
| `VALIDATION_FAILED` | `PENDING_REVIEW` (yellow) |
| `FAILED` | `CRITICAL` (red) |
| `PROCESSING_ERROR` | `CRITICAL` (red) |

**Mapping when manual confirmation = true:**

| ProcessingOutcome | → ReviewState |
|-------------------|---------------|
| `PASSED` | `PENDING_REVIEW` (yellow) |
| `LOW_CONFIDENCE` | `NEEDS_ATTENTION` (orange) |
| `VALIDATION_FAILED` | `NEEDS_ATTENTION` (orange) |
| `FAILED` | `CRITICAL` (red) |
| `PROCESSING_ERROR` | `CRITICAL` (red) |

When the user reviews any result and confirms it (with or without editing the recognized string), the `ReviewState` transitions to `MANUALLY_CONFIRMED` (blue) regardless of its previous state.

The two mapping structures are stored as configuration-level constants. The pipeline produces only `ProcessingOutcome` values — it never references `ReviewState` or colors. The review/UI layer performs the mapping.

### 8.4 Progress Reporting

The pipeline emits PySide6 signals during batch processing:

- `progress_updated(current: int, total: int)` — overall batch progress.
- `image_completed(filename: str, result: BatchResult)` — per-image completion.
- `batch_completed(results: list[BatchResult])` — batch finished.

The GUI connects to these signals to display a progress bar and populate the results review area.

### 8.5 Output Behavior

Original image files are never modified. On successful recognition (status `AUTO_ACCEPTED` or `MANUALLY_CONFIRMED`), a copy of the image is saved with the filename pattern `{identifier}_{original_stem}.ext`.

**Format rules:**

- If the original image is JPEG (`.jpg` / `.jpeg`), the copy is saved as JPEG at original quality (no re-encoding to avoid quality loss).
- If the original image is any other format (PNG, TIFF, etc.), the copy is saved as JPEG with quality factor 90.

Filename conflicts are resolved by appending a numeric suffix (e.g., `{identifier}_1_{original_stem}.jpg`).

### 8.6 Timing

The system tracks timing metrics for each run:

- **Calibration duration:** Time from calibration start to calibration completion.
- **Batch duration:** Time from batch start to batch completion.
- **Image count:** Total images processed.
- **Average time per image:** Batch duration divided by image count.

These metrics are logged after batch completion and optionally displayed in the UI.

### 8.7 Debug Export

A pipeline-level option that enables stages to export interim processing images for debugging and parameter tuning.

**Debug export modes (`DebugExportMode` enum):**

| Mode | Behavior |
|------|----------|
| `DISABLED` | No debug output (default). |
| `CALIBRATION` | Export interim images only during the calibration phase. Useful for tuning stage parameters on the example image. |
| `ALL` | Export interim images during both calibration and batch processing. Useful for diagnosing failures on specific batch images. |

**Output directory structure:**

Debug images are saved to a timestamped subfolder within the batch folder to avoid overwriting previous runs:

```
<batch_folder>/_debug_<YYYYMMDD_HHMMSS>/
    <original_image_name>/
        <stage_name>_<processing_step>.png
        <stage_name>_<processing_step>.png
        ...
    <original_image_name>/
        ...
```

For example:

```
/images/_debug_20260415_143022/
    chip_001.jpg/
        chip_region_detection_input.png
        chip_region_detection_thresholded.png
        chip_region_detection_contours.png
        feature_based_alignment_keypoints.png
        feature_based_alignment_warped.png
        text_recognition_crop.png
        text_recognition_preprocessed.png
    chip_002.jpg/
        ...
```

**Implementation responsibility:** Each stage checks the debug export mode before and after processing. If enabled for the current phase (calibration or batch), the stage saves relevant interim images (input, intermediate processing steps, output) to the appropriate directory. The specific images exported are stage-implementation-dependent — each operator decides what is useful to export for debugging purposes.

---

## 9. Host Shell Integration

The tool integrates with an existing PySide6 host shell application:

- **IToolPlugin interface:** The tool implements the host shell's plugin interface for registration, lifecycle management, and discovery. This enables the tool to be instantiated and displayed within the host shell's tab/workspace system.
- **ConfigManager:** The host shell provides a centralized configuration manager used for session-level persistence (last folder, last selected pipeline configuration).
- **Logging:** The tool uses the host shell's logging infrastructure via Python's `logging` module with a tool-specific logger name.
- **Folder handling:** The tool declares itself as a folder handler, allowing it to be opened directly from other tools in the host shell (e.g., right-clicking a folder in a file explorer and selecting "Open in SCIBIT").
- **Qt Designer support:** The tool's top-level layout is defined in a `.ui` file, enabling visual editing via Qt Designer.

---

## 10. Scientific References

### Feature Detection and Matching

- Rublee, E., Rabaud, V., Konolige, K., & Bradski, G. (2011). "ORB: An efficient alternative to SIFT or SURF." IEEE International Conference on Computer Vision (ICCV), pp. 2564–2571.
- Lowe, D. G. (2004). "Distinctive image features from scale-invariant keypoints." International Journal of Computer Vision, 60(2), pp. 91–110.

### Robust Estimation

- Fischler, M. A., & Bolles, R. C. (1981). "Random sample consensus: A paradigm for model fitting with applications to image analysis and automated cartography." Communications of the ACM, 24(6), pp. 381–395.

### Edge Detection and Contour Analysis

- Canny, J. (1986). "A computational approach to edge detection." IEEE Transactions on Pattern Analysis and Machine Intelligence, 8(6), pp. 679–698.
- Suzuki, S., & Abe, K. (1985). "Topological structural analysis of digitized binary images by border following." Computer Vision, Graphics, and Image Processing, 30(1), pp. 32–46.

### Geometric Computation

- Toussaint, G. T. (1983). "Solving geometric problems with the rotating calipers." Proceedings of the IEEE MELECON.

### Preprocessing — Adaptive Histogram Equalization

- Zuiderveld, K. (1994). "Contrast limited adaptive histogram equalization." In Graphics Gems IV, Academic Press, pp. 474–485. *(Describes the CLAHE algorithm.)*

### Preprocessing — Adaptive Thresholding

- Sauvola, J., & Pietikäinen, M. (2000). "Adaptive document image binarization." Pattern Recognition, 33(2), pp. 225–236. *(Foundation for adaptive thresholding techniques used in document/text image preprocessing.)*

### Preprocessing — Mathematical Morphology

- Serra, J. (1982). "Image Analysis and Mathematical Morphology." Academic Press. *(Foundational reference for morphological operations such as erosion, dilation, opening, and closing.)*

### OCR Engines

- PaddleOCR: Li, C., et al. (2022). "PP-OCRv3: More attempts for the improvement of ultra lightweight OCR system." arXiv:2206.03001.
- Tesseract: Smith, R. (2007). "An overview of the Tesseract OCR engine." Ninth International Conference on Document Analysis and Recognition (ICDAR), pp. 629–633.
- EasyOCR: JaidedAI. Open-source OCR library supporting 80+ languages. https://github.com/JaidedAI/EasyOCR.

---

## 11. Open Items / Future Considerations

- **Result export format:** The result export format (CSV, JSON, Excel, etc.) for batch results is not specified in this version. To be defined separately.
- **Detailed GUI layout specification:** The high-level UI architecture is described in Section 3.10, but detailed widget sizing, spacing, and visual design are not specified here. To be defined as a separate UI specification.
- **Parallel/concurrent batch processing:** Not in scope for v1. Batch processing is sequential. Can be added later with thread/process pools.
- **Additional pipeline variants:** The architecture supports adding new pipelines. Potential future variants include deep-learning-based chip detection (YOLO, etc.) or multi-identifier pipelines for chips with more than one identifier.
- **Preprocessing chaining:** Currently, preprocessing is a set of parameters within a stage. A future enhancement could allow the user to compose a custom preprocessing chain (select which sub-steps run, in what order). This would require a minor extension to the stage model.
- **Identifier pattern preset editing via GUI:** Currently, presets are loaded from a JSON file and are read-only in the GUI. A future enhancement could allow users to create and edit presets within the application.
