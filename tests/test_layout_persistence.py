"""Tests for LayoutPersistence."""

from __future__ import annotations

from pathlib import Path

from app.shell.layout import LayoutPersistence
from PySide6.QtCore import QByteArray


class TestLayoutPersistenceExists:
    """Tests for LayoutPersistence.exists."""

    def test_does_not_exist_initially(self, tmp_path: Path) -> None:
        """No state file exists before the first save."""
        lp = LayoutPersistence(tmp_path / "layout.state")
        assert not lp.exists()

    def test_exists_after_save(self, tmp_path: Path, qapp) -> None:  # noqa: ANN001
        """File exists after a successful save."""
        lp = LayoutPersistence(tmp_path / "layout.state")
        lp.save(QByteArray(b"state"))
        assert lp.exists()


class TestLayoutPersistenceSaveLoad:
    """Tests for the save/load round-trip."""

    def test_load_returns_none_when_no_file(self, tmp_path: Path) -> None:
        """Load returns None when no state file exists."""
        lp = LayoutPersistence(tmp_path / "layout.state")
        assert lp.load() is None

    def test_save_and_load_roundtrip(self, tmp_path: Path, qapp) -> None:  # noqa: ANN001
        """Data saved is identical to data loaded."""
        lp = LayoutPersistence(tmp_path / "layout.state")
        original = QByteArray(b"\x00\x01\x02\xff")
        lp.save(original)
        loaded = lp.load()
        assert loaded is not None
        assert bytes(loaded) == bytes(original)

    def test_save_creates_parent_dirs(self, tmp_path: Path, qapp) -> None:  # noqa: ANN001
        """Save creates any missing parent directories."""
        nested = tmp_path / "a" / "b" / "layout.state"
        lp = LayoutPersistence(nested)
        lp.save(QByteArray(b"x"))
        assert nested.exists()


class TestLayoutPersistenceReset:
    """Tests for LayoutPersistence.reset."""

    def test_reset_deletes_file(self, tmp_path: Path, qapp) -> None:  # noqa: ANN001
        """Reset removes the state file."""
        lp = LayoutPersistence(tmp_path / "layout.state")
        lp.save(QByteArray(b"data"))
        lp.reset()
        assert not lp.exists()

    def test_reset_noop_when_no_file(self, tmp_path: Path) -> None:
        """Reset does not raise when no file exists."""
        lp = LayoutPersistence(tmp_path / "layout.state")
        lp.reset()  # should not raise

    def test_load_after_reset_returns_none(self, tmp_path: Path, qapp) -> None:  # noqa: ANN001
        """After reset, load returns None."""
        lp = LayoutPersistence(tmp_path / "layout.state")
        lp.save(QByteArray(b"data"))
        lp.reset()
        assert lp.load() is None
