"""Nox session definitions for the VI-Toolbox project.

Nox is a task runner (similar to Makefile or tox) that creates isolated
virtual environments for each task. This ensures reproducible results
regardless of what is installed in the developer's main venv.

Available sessions (run via: nox -s <session>):
    nox -s uic          → Compile Qt Designer .ui files to Python
    nox -s lint         → Check code style and quality (no changes)
    nox -s format       → Auto-format code in place
    nox -s test         → Run the pytest test suite
    nox -s docs         → Build HTML + LaTeX API documentation from docstrings
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


def _compile_ui(session: nox.Session) -> None:
    """Run pyside6-uic on every .ui file. Assumes PySide6 is already installed."""
    ui_dir = Path("app/shell/ui")
    for ui_file in sorted(ui_dir.glob("*.ui")):
        out_file = ui_dir / f"ui_{ui_file.stem}.py"
        session.run("pyside6-uic", str(ui_file), "-o", str(out_file))
        session.log("Compiled: %s -> %s", ui_file, out_file)


def _check_lint(session: nox.Session) -> None:
    """Run ruff check + format check. Assumes ruff is already installed."""
    session.run("ruff", "check", "app", "tests")
    session.run("ruff", "format", "--check", "app", "tests")


def _run_pytest(session: nox.Session) -> None:
    """Run pytest without the e2e tests.

    Assumes the project + dev deps are already installed.  Tests marked
    ``e2e`` depend on labelled image batches and an external Tesseract
    install, so they are deselected here; run them explicitly with
    ``pytest -m e2e``.
    """
    session.run("pytest", "-m", "not e2e", *session.posargs)


@nox.session(python=PYTHON)
def uic(session: nox.Session) -> None:
    """Compile Qt Designer .ui files to Python with pyside6-uic.

    Re-run this whenever a .ui file is modified.  The generated
    ``ui_*.py`` files are committed to the repository so the app can
    be run without this step in normal development.
    """
    session.install("PySide6>=6.7,<7", "PySide6-QtAds>=4.3,<5")
    _compile_ui(session)


@nox.session(python=PYTHON)
def lint(session: nox.Session) -> None:
    """Check code style and quality with Ruff.

    Runs both the linter (style/logic checks) and the formatter
    in check-only mode (reports issues but does not modify files).
    Enforces PEP 8 (REQ-EC-005) and NumPy docstrings (REQ-EC-006).
    """
    session.install("ruff>=0.5")
    _check_lint(session)


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
def docs(session: nox.Session) -> None:
    """Build the Sphinx API documentation in HTML and LaTeX form.

    Imports every public module via Sphinx ``autodoc`` and renders the
    NumPy-style docstrings (REQ-EC-006) into a browsable site plus a
    LaTeX source tree suitable for the thesis appendix.

    Outputs:
        docs/_build/html/index.html       — browsable HTML
        docs/_build/latex/vi-toolbox.tex  — LaTeX source

    To produce a PDF from the LaTeX source, run (requires a TeX
    distribution such as MiKTeX on PATH)::

        cd docs/_build/latex
        pdflatex vi-toolbox.tex
        pdflatex vi-toolbox.tex   # second pass resolves cross-references
    """
    # opencv-python-headless provides ``cv2`` without GUI bindings — needed
    # so sphinx-autodoc-typehints can resolve forward references in modules
    # that import cv2 at module scope (e.g. core/debug.py, opencv_operator).
    session.install(".[dev]", "opencv-python-headless>=4.5")

    api_dir = Path("docs") / "api"
    if api_dir.exists():
        shutil.rmtree(api_dir)

    # Per-module .rst stubs are regenerated from the live source tree;
    # they are gitignored to avoid stale entries when modules are renamed.
    # --no-toc skips the auto-generated modules.rst overview file, since
    # index.rst already references the package root (api/app.rst) directly.
    session.run(
        "sphinx-apidoc",
        "--force",
        "--no-toc",
        "--module-first",
        "--separate",
        "--output-dir", str(api_dir),
        "app",
        "app/shell/ui/ui_main_window.py",   # generated by pyside6-uic
    )

    session.run("sphinx-build", "-b", "html", "docs", "docs/_build/html")
    session.run("sphinx-build", "-b", "latex", "docs", "docs/_build/latex")

    session.log("HTML:  docs/_build/html/index.html")
    session.log("LaTeX: docs/_build/latex/vi-toolbox.tex")


@nox.session(python=PYTHON)
def test(session: nox.Session) -> None:
    """Run the test suite with pytest.

    Installs the project with all dev dependencies into an
    isolated venv, then runs pytest. Unit tests are mandatory
    before merge/release (REQ-EC-017).
    """
    session.install(".[dev]")
    _run_pytest(session)


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
        "--add-data", "app/tools/scibit/tool.ui;app/tools/scibit",
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

    Each stage runs in sequence and any failure aborts the build before
    packaging — you cannot produce an artifact from code that fails lint
    or tests.

    Pipeline (REQ-EC-011):
        1. Compile .ui files
        2. Lint & format check (REQ-EC-018)
        3. Unit tests (REQ-EC-017)
        4. Create distributable ZIP artifact (REQ-HS-014)
    """
    _compile_ui(session)
    _check_lint(session)
    _run_pytest(session)

    import sysconfig
    site_packages = Path(sysconfig.get_path("purelib"))
    _package(session, site_packages)


@nox.session(name="build-ci", python=PYTHON)
def build_ci(session: nox.Session) -> None:
    """Full build pipeline using an isolated venv (CI distribution).

    Installs all dependencies from scratch into an isolated environment
    for a reproducible, machine-independent build.  Intended for use in
    GitLab CI (REQ-EC-020) once a CI runner is configured.

    Each stage runs in sequence and any failure aborts the build before
    packaging — you cannot produce an artifact from code that fails lint
    or tests.

    Pipeline (REQ-EC-020):
        1. Compile .ui files
        2. Lint & format check (REQ-EC-018)
        3. Unit tests (REQ-EC-017)
        4. Create distributable ZIP artifact (REQ-HS-014)
    """
    session.install(".[dev,ocr-paddle]", "pyinstaller>=6.0")

    _compile_ui(session)
    _check_lint(session)
    _run_pytest(session)

    site_packages = Path(session.virtualenv.location) / "Lib" / "site-packages"
    _package(session, site_packages)
