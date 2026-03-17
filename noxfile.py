"""Nox session definitions for the VI-Toolbox project.

Nox is a task runner (similar to Makefile or tox) that creates isolated
virtual environments for each task. This ensures reproducible results
regardless of what is installed in the developer's main venv.

Available sessions (run via: nox -s <session>):
    nox -s lint      → Check code style and quality (no changes)
    nox -s format    → Auto-format code in place
    nox -s test      → Run the pytest test suite
    nox -s build     → Run lint + test + package (the canonical build, REQ-EC-012)

Quick reference:
    nox              → Runs the default sessions (lint + test)
    nox -s build     → Full build pipeline
    nox -l           → List all available sessions
"""

import nox

# Default sessions when running just "nox" without arguments
nox.options.sessions = ["lint", "test"]

# Shared Python version
PYTHON = "3.12"


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
    # Step 1: Lint
    session.notify("lint")

    # Step 2: Test
    session.notify("test")

    # Step 3: Package as portable ZIP
    # (Placeholder — will be replaced with PyInstaller or
    #  shiv/zipapp packaging once the application is ready)
    session.log("Packaging step: not yet implemented (placeholder)")
    session.log("Future: create portable ZIP artifact (REQ-EC-020)")
