# Identifier Recognition Pipelines

Two processing pipelines are proposed for identifying and recognizing chip identifiers within image batches. Both share a common three-phase structure — **Set Reference Data**, **Process Batch**, and **OCR** — but differ in how the identifier region is localized.

### Actor Definitions

Each step is attributed to one of three actors:

- **Framework** — A direct call to an external library or framework (e.g., PaddleOCR text detection, OpenCV contour finding). No custom logic; we invoke it and receive its output.
- **Program** — Our own application logic that processes, filters, transforms, or combines framework outputs. This is where the core contribution of this work resides.
- **User** — Requires human interaction through the GUI (confirmation, selection, manual input).

---

## Shared Prerequisite: OCR Engine Selection

Both pipelines ultimately rely on an OCR engine to convert the localized identifier region into text. Before detailing the pipelines, the OCR considerations that apply to both are outlined.

### Text Detection vs. Text Recognition

OCR broadly consists of two stages:

1. **Text Detection** — Locating *where* text exists in an image (outputs bounding boxes around text regions).
2. **Text Recognition** — Decoding *what* the detected text says (outputs character sequences).

Modern OCR frameworks (e.g., PaddleOCR, EasyOCR, TrOCR) bundle both stages into a single pipeline. However, for this use case, the two stages serve different roles depending on the pipeline:

- In Pipeline 1, text detection is used during calibration (to find all text regions) and during batch processing (to find candidate regions), while text recognition is applied only to the final selected region.
- In Pipeline 2, text detection is not used for localization (the ROI replaces it), so only text recognition is needed during batch processing.

### Preprocessing for OCR

Regardless of pipeline, the following preprocessing steps improve OCR reliability and should be applied to the cropped identifier region before recognition. Note: some OCR frameworks (e.g., PaddleOCR) perform parts of this preprocessing internally. The implementation will use an abstract wrapper class for different framework options, so these steps are called uniformly — the wrapper determines whether each step performs actual processing or passes through, depending on the chosen framework's capabilities.

- **Polarity normalization** — Ensure dark text on light background. If the batch uses bright-on-dark identifiers (determined during calibration), invert the region.
- **Deskew** — Correct the fine rotation (±5° within a batch). Use the Hough transform or minimum area rectangle of the text region to estimate the skew angle.
- **Brightness normalization** — Apply histogram equalization or adaptive normalization to compensate for brightness variation within the batch.
- **Upscaling** — If the cropped identifier region is small in pixel terms, upscale to a resolution where character height is at least ~32px, which is the expected input size for most recognition models.

### Post-OCR Validation

After recognition, the raw OCR output should be validated:

- **Regex matching** — Check against the user-configured regular expression pattern (stored in an editable config file). If the result does not match, flag it as uncertain.
- **Batch pattern consistency** — As identifiers are recognized across a batch, a naming pattern may emerge (e.g., sequential numbering like C071, C072, C073...). Results that deviate structurally from the emerging pattern should be flagged.
- **Confidence thresholding** — If the OCR engine provides character-level confidence scores, flag results with low confidence characters for manual review rather than silently accepting them.

---

## Pipeline 1: Normalized Coordinates via Chip Shape Recognition

This pipeline uses the physical chip as a coordinate reference frame. By detecting the chip boundary, the identifier's position and size can be expressed as normalized proportions of the chip — invariant to image resolution and zoom level.

### 1.1 Set Reference Data (First Image)

| Step | Actor | Description |
|------|-------|-------------|
| 1.1.1 | Framework | **Run chip area recognition.** Apply adaptive thresholding to separate the chip from the monotone gel pad background. Find contours. Compute bounding boxes or minimum area rectangles for detected regions. |
| 1.1.2 | Program | **Filter chip candidates.** Reject contours touching the image border (neighboring chip fragments from the gel pad). Select the largest remaining contour as the chip candidate. |
| 1.1.3 | User | **Confirm or reject chip area result.** The detected chip boundary is displayed as an overlay on the image. The user either confirms the result, or rejects it. On rejection, the user chooses between: (a) retry automatic detection with different parameters, or (b) manually draw the chip boundary. |
| 1.1.4 | Program | **Handle rejection — retry (if chosen).** Adjust the detection parameters and retry from 1.1.1. The adjustment strategy is framework-dependent (e.g., for threshold-based detection: vary threshold value, switch between global and adaptive thresholding, adjust morphological operations; for learned detectors: adjust confidence thresholds). The program should expose an abstract "retry with alternative settings" mechanism that cycles through a predefined set of parameter configurations. |
| 1.1.5 | User | **Handle rejection — manual drawing (if chosen).** The user manually draws the chip boundary on the image. |
| 1.1.6 | Program | **Save chip aspect ratio.** Store the width-to-height ratio of the confirmed (or manually drawn) chip bounding box as reference for subsequent images. |
| 1.1.7 | Framework | **Run text region detection.** Within the confirmed chip area, run the text detection stage of the OCR framework to locate all text regions (identifier, brand name, version strings, etc.). |
| 1.1.8 | User | **Select the identifier region.** All detected text regions are highlighted. The user clicks/selects the one that corresponds to the identifier to be used for renaming. If no detected region matches the identifier, the user can manually draw the identifier region as a fallback. |
| 1.1.9 | Program | **Compute and save normalized identifier reference.** Express the identifier's position and size as proportions of the chip bounding box: relative x-offset, relative y-offset, relative width, relative height. Also determine and store the identifier's polarity (bright-on-dark or dark-on-bright) and base rotation angle. |
| 1.1.10 | Program | **Preprocess identifier region.** Crop the selected identifier region and apply preprocessing (polarity normalization, deskew, brightness normalization, upscaling — see Shared Prerequisite above). |
| 1.1.11 | Framework | **Run text recognition on identifier.** Apply the OCR recognition model to the preprocessed identifier region. |
| 1.1.12 | User | **Confirm OCR result.** The recognized text is displayed to the user (e.g., "Recognized identifier: C074-26"). The user confirms if correct, or manually corrects the text. This serves three purposes: (1) validates that the preprocessing and OCR configuration work for this batch, (2) provides a confirmed ground truth identifier that can be used as a reference pattern for batch consistency checking, and (3) gives early failure detection — if OCR fails on the calibration image (typically the best example), it signals that settings may need adjustment before processing the entire batch. |
| 1.1.13 | Program | **Save confirmed identifier as reference pattern.** Store the confirmed identifier string. Extract structural properties (length, character classes, separators) to use for batch pattern consistency validation during batch processing. |

### 1.2 Process Batch (Each Subsequent Image)

| Step | Actor | Description |
|------|-------|-------------|
| 1.2.1 | Framework | **Run chip area recognition.** Same method as 1.1.1 — threshold and contour detection on the image. |
| 1.2.2 | Program | **Filter and validate chip detection.** Apply the same border-touching filter as 1.1.2. Then compare the detected chip's aspect ratio against the saved reference. If the ratio deviates beyond a tolerance threshold, flag the detection as potentially incorrect (e.g., a neighboring chip fragment was selected instead). In case of failure, fall back to the next-largest valid contour, or flag for manual review. |
| 1.2.3 | Framework | **Run text region detection.** *(Potentially optional — see note below.)* Within the detected chip area, run text detection to locate all candidate text regions. |
| 1.2.4 | Program | **Select identifier candidate.** *(Potentially optional — see note below.)* For each detected text region, compute its normalized position and size relative to the chip bounding box. Score each candidate by geometric similarity to the saved reference (e.g., Euclidean distance in normalized coordinate space). Select the closest match. |

> **Note on steps 1.2.3–1.2.4:** If the normalized coordinates from calibration prove sufficiently accurate and chip detection is reliable, these two steps could be replaced by a direct crop of the identifier region based on the saved normalized coordinates applied to the detected chip bounding box. This would skip text detection entirely during batch processing, reducing per-image processing time and eliminating a potential failure point. Whether this simplification is viable depends on how consistently the identifier position holds within a batch — to be evaluated during implementation.

### 1.3 OCR (Applied to Selected Region)

| Step | Actor | Description |
|------|-------|-------------|
| 1.3.1 | Program | **Preprocess identifier region.** Crop the selected text region, apply polarity normalization, deskew, brightness normalization, and upscale as needed (see Shared Prerequisite above). |
| 1.3.2 | Framework | **Run text recognition.** Apply the OCR recognition model to the preprocessed region to obtain the character sequence. |
| 1.3.3 | Program | **Validate result.** Apply regex matching, batch pattern consistency check, and confidence thresholding. Classify result as accepted or flagged. |
| 1.3.4 | Program | **Rename or queue.** If accepted: rename the file using the recognized identifier (with duplicate handling via numeric suffix). If flagged: add to the manual review queue. |

### 1.4 Manual Review (After Batch Completion)

| Step | Actor | Description |
|------|-------|-------------|
| 1.4.1 | Program | **Present flagged images.** Display each flagged image with a zoomable view of the identifier region and a text field pre-filled with the best OCR guess (if available). |
| 1.4.2 | User | **Correct or confirm.** The user types the correct identifier or confirms the suggestion. |
| 1.4.3 | Program | **Rename.** Apply the user-provided identifier to the filename. |

---

## Pipeline 2: ROI Selection with Tolerance Correction

This pipeline bypasses chip detection entirely. The user manually selects a region of interest on the first image, and subsequent images are processed by searching for text within a tolerance-expanded version of that region.

### 2.1 Set Reference Data (First Image)

| Step | Actor | Description |
|------|-------|-------------|
| 2.1.1 | User | **Select ROI on image.** The user draws a rectangular region around the identifier on the first image. This defines the approximate location and size of the identifier in pixel coordinates. |
| 2.1.2 | Framework | **Run text region detection within ROI.** Run the text detection stage within (or slightly around) the user-selected ROI to snap to precise text boundaries. |
| 2.1.3 | User | **Confirm detected text region.** If text detection found a region within the ROI, display it for confirmation. If multiple regions are found, let the user select. If none are found, use the raw ROI as-is. |
| 2.1.4 | Program | **Save ROI reference and image resolution.** Store the confirmed region's position and size in absolute pixel coordinates. Also store the reference image's resolution (width × height) for rescaling in batch processing. Determine and store the identifier's polarity and base rotation angle. |
| 2.1.5 | Program | **Preprocess identifier region.** Crop the confirmed identifier region and apply preprocessing (polarity normalization, deskew, brightness normalization, upscaling — see Shared Prerequisite above). |
| 2.1.6 | Framework | **Run text recognition on identifier.** Apply the OCR recognition model to the preprocessed identifier region. |
| 2.1.7 | User | **Confirm OCR result.** The recognized text is displayed to the user. The user confirms if correct, or manually corrects the text. Same purposes as Pipeline 1 step 1.1.12: validates preprocessing/OCR configuration, provides a ground truth reference pattern, and offers early failure detection. |
| 2.1.8 | Program | **Save confirmed identifier as reference pattern.** Store the confirmed identifier string. Extract structural properties (length, character classes, separators) to use for batch pattern consistency validation during batch processing. |

### 2.2 Process Batch (Each Subsequent Image)

| Step | Actor | Description |
|------|-------|-------------|
| 2.2.1 | Program | **Resize image to reference resolution.** Scale the current image to match the saved reference resolution. This compensates for zoom and resolution variation across the batch, keeping the ROI coordinates applicable. Note: this assumes image aspect ratios within a batch are sufficiently similar; significant aspect ratio deviation may reduce accuracy. The choice of whether to resize the reference image during calibration or the batch images during processing should be considered based on performance and quality trade-offs (e.g., downscaling large batch images to a smaller reference is fast but loses detail; upscaling a small reference during calibration preserves batch image quality). |
| 2.2.2 | Program | **Compute search region with tolerance.** Apply the saved ROI pixel coordinates to the resized image. Expand the region by a configurable tolerance margin (e.g., ±30–50% in each direction) to account for remaining positional variation within the batch. |
| 2.2.3 | Framework | **Run text region detection in search region.** Detect all text regions within the expanded search area. |
| 2.2.4 | Program | **Select best candidate.** If multiple text regions are found, select the one closest to the center of the expected position (the original ROI center). If only one is found, use it. If none are found, flag for manual review. |

### 2.3 OCR (Applied to Selected Region)

Identical to Pipeline 1, steps 1.3.1 through 1.3.4.

### 2.4 Manual Review (After Batch Completion)

Identical to Pipeline 1, steps 1.4.1 through 1.4.3.

---

## Comparison

| Aspect | Pipeline 1 (Chip Shape) | Pipeline 2 (ROI Tolerance) |
|--------|--------------------------|----------------------------|
| **Robustness to zoom/resolution variation** | High — normalized to chip, invariant to image scale | Medium — image resizing compensates for resolution differences, but assumes sufficiently similar aspect ratios within a batch |
| **User effort during calibration** | Two confirmations (chip area + identifier selection) | One action (draw ROI), optional confirmation |
| **Dependency on image properties** | Requires detectable chip boundary (monotone background with gap) | No assumptions about chip detectability; assumes roughly consistent aspect ratios |
| **Failure mode** | Chip detection fails → entire pipeline fails for that image | Aspect ratio mismatch → distorted ROI mapping; tolerance too small → misses identifier; too large → picks wrong text |
| **Implementation complexity** | Higher — requires chip segmentation + normalized coordinate math | Lower — basic image resizing + coordinate mapping with padding |
| **Suitability** | Best when chip boundary is reliably visible and zoom variation is large | Best when images have similar aspect ratios or when chip boundary is unreliable |
