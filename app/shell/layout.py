"""Dock layout state persistence between sessions (REQ-HS-007)."""

from __future__ import annotations

import json
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

    @property
    def _geometry_file(self) -> Path:
        return self._state_file.with_name("geometry.state")

    @property
    def _session_file(self) -> Path:
        return self._state_file.with_name("session.json")

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

    def save_geometry(self, geometry: QByteArray) -> None:
        """Write the main window geometry to disk.

        Parameters
        ----------
        geometry : QByteArray
            Serialised geometry from :meth:`QMainWindow.saveGeometry`.
        """
        try:
            self._geometry_file.parent.mkdir(parents=True, exist_ok=True)
            self._geometry_file.write_bytes(bytes(geometry))
            _logger.debug("Geometry saved to %s", self._geometry_file)
        except OSError as exc:
            _logger.error("Failed to save geometry: %s", exc)

    def load_geometry(self) -> QByteArray | None:
        """Load the main window geometry from disk.

        Returns
        -------
        QByteArray | None
            Persisted geometry, or ``None`` if no geometry file exists.
        """
        if not self._geometry_file.exists():
            return None
        try:
            data = self._geometry_file.read_bytes()
            _logger.debug("Geometry loaded from %s", self._geometry_file)
            return QByteArray(data)
        except OSError as exc:
            _logger.error("Failed to load geometry: %s", exc)
            return None

    def save_open_tools(self, tool_names: list[str]) -> None:
        """Persist the ordered list of open tool names for the next session.

        Parameters
        ----------
        tool_names : list[str]
            Registered tool names in the order they were opened.  Duplicates
            are preserved so multi-instance tools are reopened the correct
            number of times with matching instance keys.
        """
        try:
            self._session_file.parent.mkdir(parents=True, exist_ok=True)
            self._session_file.write_text(json.dumps(tool_names), encoding="utf-8")
            _logger.debug("Session saved to %s", self._session_file)
        except OSError as exc:
            _logger.error("Failed to save session: %s", exc)

    def load_open_tools(self) -> list[str] | None:
        """Load the ordered list of open tool names from the previous session.

        Returns
        -------
        list[str] | None
            Ordered tool names, or ``None`` if no session file exists.
        """
        if not self._session_file.exists():
            return None
        try:
            data = json.loads(self._session_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                _logger.debug("Session loaded from %s", self._session_file)
                return data
        except (OSError, json.JSONDecodeError) as exc:
            _logger.error("Failed to load session: %s", exc)
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
        """Delete the persisted layout and geometry state files.

        No-op for each file that does not exist.
        """
        for path in (self._state_file, self._geometry_file, self._session_file):
            if path.exists():
                try:
                    path.unlink()
                    _logger.info("State file deleted: %s", path)
                except OSError as exc:
                    _logger.error("Failed to reset layout: %s", exc)
