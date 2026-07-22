"""User role management based on Windows account names (REQ-HS-009)."""

from __future__ import annotations

import getpass
import json
import logging
from enum import Enum
from pathlib import Path

_logger = logging.getLogger("vi_toolbox.core.roles")


class Role(Enum):
    """User roles defining permission levels.

    Attributes
    ----------
    OPERATOR : str
        Standard user — view and basic operation permissions.
    ENGINEER : str
        Advanced user — configuration and analysis permissions.
    ADMIN : str
        Administrator — full access.
    """

    OPERATOR = "operator"
    ENGINEER = "engineer"
    ADMIN = "admin"


class RoleManager:
    """Resolves the current user's role from a JSON mapping file.

    On construction the Windows username is read via :mod:`getpass` and
    looked up in ``<config_dir>/roles.json``.  If no mapping exists the
    user defaults to :attr:`Role.OPERATOR`.

    Parameters
    ----------
    config_dir : Path
        Directory that may contain a ``roles.json`` mapping file.

    Examples
    --------
    >>> manager = RoleManager(Path("config"))
    >>> manager.get_role()
    <Role.OPERATOR: 'operator'>
    """

    _ROLES_FILE = "roles.json"

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._current_user: str = self._query_windows_account()
        self._user_role: Role = self._load_role()
        _logger.info(
            "Role resolved: user=%s role=%s",
            self._current_user,
            self._user_role.value,
        )

    def get_current_user(self) -> str:
        """Return the current Windows username.

        Returns
        -------
        str
            Username as returned by the operating system.
        """
        return self._current_user

    def get_role(self) -> Role:
        """Return the resolved role for the current user.

        Returns
        -------
        Role
            The user's assigned role.
        """
        return self._user_role

    def has_permission(self, permission: str) -> bool:
        """Return whether the current role grants *permission*.

        The permission hierarchy is ADMIN > ENGINEER > OPERATOR.
        Tool-level access rules are not yet implemented; all tools are
        accessible to all roles.

        Parameters
        ----------
        permission : str
            Permission identifier (e.g. the tool name).

        Returns
        -------
        bool
            ``True`` if the current role has the given permission.
        """
        _ = permission  # reserved for future role-based access rules
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _query_windows_account(self) -> str:
        """Return the current Windows username via :func:`getpass.getuser`.

        Returns
        -------
        str
            Username string.
        """
        return getpass.getuser()

    def _load_role(self) -> Role:
        """Load the role mapping from disk and resolve for the current user.

        Returns
        -------
        Role
            Resolved role, defaulting to :attr:`Role.OPERATOR`.
        """
        roles_file = self._config_dir / self._ROLES_FILE
        if not roles_file.exists():
            return Role.OPERATOR
        try:
            with roles_file.open(encoding="utf-8") as fh:
                mapping: dict[str, str] = json.load(fh)
            role_str = mapping.get(self._current_user, "operator").lower()
            return Role(role_str)
        except (json.JSONDecodeError, ValueError) as exc:
            _logger.warning("Failed to load roles.json: %s — defaulting to OPERATOR", exc)
            return Role.OPERATOR
