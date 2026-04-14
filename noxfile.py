"""Nox session definitions for the VI-Toolbox project.

Nox is a task runner (similar to Makefile or tox) that creates isolated
virtual environments for each task. This ensures reproducible results
regardless of what is installed in the developer's main venv.

Available sessions (run via: nox -s <session>):
    nox -s uic          → Compile Qt Designer .ui files to Python
    nox -s lint         → Check code style and quality (no changes)
    nox -s format       → Auto-format code in place
    nox -s test         → Run the pytest test suite
    nox -s lock         → Regenerate requirements*.txt lockfiles via pip-compile
    nox -s build-local  → lint + test + package using active .venv (local use)
    nox -s build-ci     → lint + test + package using isolated venv (CI use)

Quick reference:
    nox                  → Runs the default sessions (lint + test)
    nox -s build-local   → Build and package from your local .venv
    nox -s build-ci      → Reproducible build for GitLab CI
    nox -s lock          → Update lockfiles after changing pyproject.toml
    nox -l               → List all available sessions
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


def _package(session: nox.Session, site_packages: Path) -> None:
    """Run PyInstaller and assemble the portable ZIP artifact.

    Shared implementation used by both ``build-local`` and ``build-ci``.
    The only difference between the two sessions is where site-packages
    lives, which affects the paddle copy step.
    """
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
        # paddleocr/paddlex use dynamic imports and ship YAML configs and other
        # data files — --collect-all bundles Python modules, data, and binaries.
        "--collect-all", "paddleocr",
        "--collect-all", "paddlex",
        "app/__main__.py",
    )

    # paddle (paddlepaddle) is a native package that PyInstaller cannot collect
    # automatically on Windows — it skips it with "not a package" warning.
    # Copy the entire paddle directory from site-packages into _internal/ where
    # the bundled Python looks for packages.
    internal_dir = Path("dist") / "vi-toolbox" / "_internal"
    paddle_src = site_packages / "paddle"
    paddle_dst = internal_dir / "paddle"
    if paddle_src.exists():
        shutil.copytree(paddle_src, paddle_dst, dirs_exist_ok=True)
        session.log("Manually copied paddle: %s -> %s", paddle_src, paddle_dst)
    else:
        session.warn("paddle package not found: %s", paddle_src)

    # paddleocr/paddlex use importlib.metadata at runtime to verify that their
    # dependencies are installed (e.g. the ocr-core extra check in deps.py).
    # PyInstaller only copies a handful of .dist-info directories — the rest are
    # missing, so is_dep_available() returns False and DependencyError is raised.
    # Copy every .dist-info from site-packages into _internal/ so that all
    # importlib.metadata calls resolve correctly in the frozen bundle.
    copied = 0
    for dist_info in site_packages.glob("*.dist-info"):
        dst = internal_dir / dist_info.name
        if not dst.exists():
            shutil.copytree(dist_info, dst)
            copied += 1
    session.log("Copied %d missing .dist-info directories into _internal/", copied)

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


@nox.session(name="build-local", venv_backend="none")
def build_local(session: nox.Session) -> None:
    """Full build pipeline using the active .venv (local distribution).

    Uses whatever is installed in the currently active virtual environment,
    so activate your .venv before running:
        .venv\\Scripts\\activate
        nox -s build-local

    Pipeline (REQ-EC-012):
        1. Compile .ui files
        2. Lint & format check (REQ-EC-019)
        3. Unit tests (REQ-EC-018)
        4. Create distributable ZIP artifact (REQ-EC-020)
    """
    session.notify("uic")
    session.notify("lint")
    session.notify("test")

    import sysconfig
    site_packages = Path(sysconfig.get_path("purelib"))
    _package(session, site_packages)


@nox.session(name="build-ci", python=PYTHON)
def build_ci(session: nox.Session) -> None:
    """Full build pipeline using an isolated venv (CI distribution).

    Installs all dependencies from scratch into an isolated environment
    for a reproducible, machine-independent build.  Intended for use in
    GitLab CI (REQ-EC-023) once a CI runner is configured.

    Pipeline (REQ-EC-012):
        1. Compile .ui files
        2. Lint & format check (REQ-EC-019)
        3. Unit tests (REQ-EC-018)
        4. Create distributable ZIP artifact (REQ-EC-020)
    """
    session.notify("uic")
    session.notify("lint")
    session.notify("test")

    session.install(".[dev,ocr-paddle]", "pyinstaller>=6.0")
    site_packages = Path(session.virtualenv.location) / "Lib" / "site-packages"
    _package(session, site_packages)
