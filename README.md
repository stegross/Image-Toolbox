# VI-Toolbox

**VI-Toolbox** is an extensible desktop application of tools that support visual inspection.

> **Platform:** Windows only · **Python:** 3.12+ · **GUI:** PySide6 + Qt Advanced Docking System

---

## Features

- **Docking host shell** — arrange tools freely via drag-and-drop docking; window
  and dock layouts persist between sessions.
- **Pluggable tool architecture** — new tools register statically against a common
  plugin interface without touching the application core.
- **Role management** — OPERATOR / ENGINEER / ADMIN roles resolved from Windows
  accounts.
- **Built-in base tools** — Image Viewer, File Explorer, and a central Log Viewer.
- **SCIBIT identification tool** — batch OCR for chip identifiers with a
  calibration → processing → review workflow, ROI selection on high-resolution
  images, regex validation, and manual correction of low-confidence results.
- **Multiple OCR backends** — PaddleOCR, EasyOCR, and Tesseract, each lazy-loaded
  and selectable at runtime; OpenCV for classical alignment/detection.
- **Single-executable distribution** — packaged with PyInstaller.

## Architecture

The application is organised in four layers:

| Layer | Responsibility | Key modules |
|-------|----------------|-------------|
| **Application core** | Lifecycle, roles, config, logging | `app/core/` |
| **Shell / UI** | Main window, docking, layout persistence | `app/shell/` |
| **Tool interface** | Plugin contract + static registry | `app/plugin/` |
| **Tools** | Base tools + SCIBIT extension | `app/tools/` |

SCIBIT itself uses a modular **Operation / Operator / Stage / Pipeline** design:
three pipeline variants (feature-based alignment, contour/direct-ROI) composed of
reusable stages, with OCR delegated to interchangeable operator backends.

```
app/
  __main__.py            # entry point (python -m app)
  core/                  # application, roles, config, logging
  shell/                 # main_window, docking_manager, layout
  plugin/                # base (IToolPlugin), registry, categories
  tools/
    image_viewer/        # base tool
    file_explorer/       # base tool
    log_viewer/          # base tool
    scibit/              # SCIBIT identification tool
      core/  pipelines/  stages/  operators/  ui/  config/
```

## Requirements

- Windows
- Python 3.12 or newer
- For SCIBIT OCR: at least one OCR backend (see below). The Tesseract backend
  additionally requires the Tesseract binary on `PATH`.

## Installation

```powershell
# Clone
git clone https://gitlab.fe.hhi.de/backend-and-packaging/vi-toolbox.git
cd vi-toolbox

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install the application
pip install -e .
```

### Optional OCR backends

OCR backends are optional — install the one(s) you intend to use:

```powershell
pip install -e ".[ocr-paddle]"      # PaddleOCR (recommended, used in research)
pip install -e ".[ocr-easy]"        # EasyOCR
pip install -e ".[ocr-tesseract]"   # Tesseract (needs the Tesseract binary on PATH)
pip install -e ".[ocr]"             # all of the above
```

### Development install

```powershell
pip install -e ".[dev,ocr]"
```

## Usage

Launch the application:

```powershell
python -m app
```

or, once installed, via the console script:

```powershell
vi-toolbox
```

On first launch the File Explorer and Log Viewer open automatically. Open the
**SCIBIT** tool from the navigation bar to run the identifier-recognition
workflow: select an image folder, calibrate on the first image (ROI + settings),
run the batch, then review and correct any low-confidence results.

## Development

The project uses [nox](https://nox.thea.codes/) for task automation.

```powershell
nox -s lint          # ruff lint
nox -s format        # ruff format
nox -s test          # pytest + pytest-qt
nox -s uic           # compile Qt Designer .ui files
nox -s docs          # build Sphinx HTML documentation
nox -s lock          # regenerate the dependency lockfile
nox -s build-local   # build a portable distribution locally
```

- **Linting/formatting:** ruff, with the NumPy docstring convention (PEP 8 + `N`, `D`, `UP`, `I`).
- **Testing:** pytest with pytest-qt (`qt_api = pyside6`).
- **Docs:** Sphinx + Furo; API reference under `docs/`.

## Documentation

API documentation is generated with Sphinx. Build it with `nox -s docs` and open
the resulting HTML output. Design documents (UML, requirements) live under `docs/`.