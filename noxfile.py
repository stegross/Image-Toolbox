"""Nox session definitions for the VI-Toolbox project.

Nox is a task runner (similar to Makefile or tox) that creates isolated
virtual environments for each task. This ensures reproducible results
regardless of what is installed in the developer's main venv.

Available sessions (run via: nox -s <session>):
    nox -s uic       → Compile Qt Designer .ui files to Python
    nox -s lint      → Check code style and quality (no changes)
    nox -s format    → Auto-format code in place
    nox -s test      → Run the pytest test suite
    nox -s lock      → Regenerate requirements*.txt lockfiles via pip-compile
    nox -s build     → Run uic + lint + test + package (REQ-EC-012)

Quick reference:
    nox              → Runs the default sessions (lint + test)
    nox -s build     → Full build pipeline
    nox -s lock      → Update lockfiles after changing pyproject.toml
    nox -l           → List all available sessions
"""

import shutil
from pathlib import Path

import nox

# Default sessions when running just "nox" without arguments
nox.options.sessions = ["lint", "test"]

# Shared Python version
PYTHON = "3.12"


@nox.session(python=PYTHON)
def uic(session: nox.Session) -> None:
    """Compile Qt Designer .ui files to Python with pyside6-uic.

    Re-run this whenever a .ui file is modified.  The generated
    ``ui_*.py`` files are committed to the repository so the app can
    be run without this step in normal development.
    """
    session.install("PySide6>=6.7,<7", "PySide6-QtAds>=4.3,<5")
    ui_dir = Path("app/shell/ui")
    for ui_file in sorted(ui_dir.glob("*.ui")):
        out_file = ui_dir / f"ui_{ui_file.stem}.py"
        session.run("pyside6-uic", str(ui_file), "-o", str(out_file))
        session.log("Compiled: %s -> %s", ui_file, out_file)


@nox.session(python=PYTHON)
def lint(session: nox.Session) -> None:
    """Check code style and quality with Ruff.

    Runs both the linter (style/logic checks) and the formatter
    in check-only mode (reports issues but does not modify files).
    Enforces PEP 8 (REQ-EC-005) and NumPy docstrings (REQ-EC-006).
    """
    session.install("ruff>=0.5")
    session.run("ruff", "check", "app", "tests")
    session.run("ruff", "format", "--check", "app", "tests")


@nox.session(python=PYTHON)
def format(session: nox.Session) -> None:
    """Auto-format code in place with Ruff.

    Sorts imports and applies consistent formatting.
    Run this before committing.
    """
    session.install("ruff>=0.5")
    session.run("ruff", "check", "--fix", "app", "tests")
    session.run("ruff", "format", "app", "tests")


@nox.session(python=PYTHON)
def lock(session: nox.Session) -> None:
    """Regenerate pinned lockfiles from pyproject.toml via pip-compile.

    Run this whenever pyproject.toml dependencies change.  The generated
    files should be committed so every developer and CI job installs
    identical package versions.

    Output files:
        requirements.txt      — core runtime deps (for end-user installs)
        requirements-dev.txt  — runtime + dev + all OCR extras (for developers)
    """
    session.install("pip-tools>=7.0")
    # Core runtime lockfile
    session.run(
        "pip-compile",
        "--output-file=requirements.txt",
        "--strip-extras",
        "pyproject.toml",
    )
    # Full developer lockfile (dev tools + all OCR backends)
    session.run(
        "pip-compile",
        "--extra=dev",
        "--extra=ocr",
        "--output-file=requirements-dev.txt",
        "--strip-extras",
        "pyproject.toml",
    )
    session.log("Lockfiles updated: requirements.txt, requirements-dev.txt")


@nox.session(python=PYTHON)
def test(session: nox.Session) -> None:
    """Run the test suite with pytest.

    Installs the project with all dev dependencies into an
    isolated venv, then runs pytest. Unit tests are mandatory
    before merge/release (REQ-EC-018).
    """
    session.install(".[dev]")
    session.run("pytest", *session.posargs)


@nox.session(python=PYTHON)
def build(session: nox.Session) -> None:
    """Full build pipeline: lint → test → package.

    This is the canonical local build command (REQ-EC-012):
        nox -s build

    The pipeline mirrors what the GitLab CI runs (REQ-EC-023):
        1. Lint & format check (quality gate, REQ-EC-019)
        2. Unit tests (REQ-EC-018)
        3. Create distributable ZIP artifact (REQ-EC-020)
    """
    # Step 1: Compile .ui files
    session.notify("uic")

    # Step 2: Lint
    session.notify("lint")

    # Step 2: Test
    session.notify("test")

    # Step 3: Package as portable ZIP (REQ-EC-020)
    session.install(".[dev]", "pyinstaller>=6.0")
    session.run(
        "pyinstaller",
        "--onedir",
        "--name", "vi-toolbox",
        "--noconfirm",
        # Include Qt Designer .ui files (not auto-detected by PyInstaller)
        "--add-data", "app/shell/ui/main_window.ui;app/shell/ui",
        "--add-data", "app/tools/identification_tool/tool.ui;app/tools/identification_tool",
        # OCR engine modules are loaded dynamically via importlib.import_module
        # in factory.py — PyInstaller cannot detect them via static analysis.
        "--hidden-import", "app.tools.identification_tool.ocr.paddleocr_engine",
        "--hidden-import", "app.tools.identification_tool.ocr.easyocr_engine",
        "--hidden-import", "app.tools.identification_tool.ocr.tesseract",
        "app/__main__.py",
    )

    # Copy bundled PaddleX models/fonts next to the executable so the app
    # finds them via PADDLEX_HOME (set in app/__main__.py when frozen).
    paddlex_src = Path.home() / ".paddlex"
    paddlex_dst = Path("dist") / "vi-toolbox" / "paddlex_data"
    if paddlex_src.exists():
        shutil.copytree(paddlex_src, paddlex_dst, dirs_exist_ok=True)
        session.log("Copied PaddleX data: %s -> %s", paddlex_src, paddlex_dst)
    else:
        session.warn("~/.paddlex not found — bundle will download models on first run")

    # Zip the entire dist/vi-toolbox/ folder into dist/vi-toolbox.zip
    zip_stem = Path("dist") / "vi-toolbox"
    shutil.make_archive(str(zip_stem), "zip", "dist", "vi-toolbox")
    session.log("Artifact created: %s", zip_stem.with_suffix(".zip"))
