"""Dock layout state persistence between sessions (REQ-HS-007)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray

_logger = logging.getLogger("vi_toolbox.shell.layout")


class LayoutPersistence:
    """Saves and restores the docking layout state between sessions.

    Serialises the raw bytes returned by
    :meth:`~app.shell.docking_manager.DockingManager.save_state` to a
    single binary file and reloads them on startup.

    Parameters
    ----------
    state_file : Path
        File path where the dock manager state is persisted.
    """

    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file

    def save(self, state: QByteArray) -> None:
        """Write the dock manager state to disk.

        Parameters
        ----------
        state : QByteArray
            Serialised state from :meth:`CDockManager.saveState`.
        """
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_bytes(bytes(state))
            _logger.debug("Layout saved to %s", self._state_file)
        except OSError as exc:
            _logger.error("Failed to save layout: %s", exc)

    def load(self) -> QByteArray | None:
        """Load the dock manager state from disk.

        Returns
        -------
        QByteArray | None
            Persisted state, or ``None`` if no state file exists.
        """
        if not self._state_file.exists():
            return None
        try:
            data = self._state_file.read_bytes()
            _logger.debug("Layout loaded from %s", self._state_file)
            return QByteArray(data)
        except OSError as exc:
            _logger.error("Failed to load layout: %s", exc)
            return None

    def exists(self) -> bool:
        """Return whether a saved layout state file exists on disk.

        Returns
        -------
        bool
            ``True`` if the state file is present.
        """
        return self._state_file.exists()

    def reset(self) -> None:
        """Delete the persisted layout state file.

        No-op if the file does not exist.
        """
        if self._state_file.exists():
            try:
                self._state_file.unlink()
                _logger.info("Layout state reset (file deleted).")
            except OSError as exc:
                _logger.error("Failed to reset layout: %s", exc)
