"""Application lifecycle: bootstraps all subsystems and starts the event loop."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.core.config import ConfigManager
from app.core.logging import get_logger, initialize_logging
from app.core.roles import RoleManager
from app.plugin.registry import ToolRegistry
from app.shell.layout import LayoutPersistence
from app.shell.main_window import MainWindow

# User-specific data directory for configs, logs, and layout state
_APP_DATA_DIR = Path.home() / ".vi_toolbox"

_log = get_logger("core.application")


class Application:
    """Bootstraps and runs the VI-Toolbox application.

    Initialises all subsystems in the correct order (logging → roles →
    config → UI) and then hands control to the Qt event loop.

    Examples
    --------
    Launch from the command line::

        python -m app
    """

    def run(self) -> int:
        """Initialise all subsystems, show the window, and enter the event loop.

        Returns
        -------
        int
            Exit code returned by :meth:`QApplication.exec`.
        """
        qt_app = self._create_qt_app()

        self._initialize_logging()
        role_manager = self._check_roles()
        config_manager = self._initialize_config()

        # User config root (for user-created pipeline configs, session
        # state, layout, etc.)
        user_root = self._get_user_config_root()
        self._validate_bundled_configs()

        tool_registry = ToolRegistry()

        layout_persistence = LayoutPersistence(state_file=user_root / "layout.state")

        main_window = self._create_main_window(
            tool_registry,
            role_manager,
            config_manager,
            layout_persistence,
            user_config_dir=user_root,
        )
        main_window.show()

        return qt_app.exec()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_qt_app(self) -> QApplication:
        """Create and configure the :class:`QApplication` instance.

        Returns
        -------
        QApplication
            Configured application instance.
        """
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        # High-DPI scaling is enabled by default in Qt6 / PySide6.
        # Use PassThrough rounding so fractional scale factors are exact.
        app.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
        app.setApplicationName("VI - Toolbox")
        app.setApplicationVersion("0.1.0")
        return app  # type: ignore[return-value]

    def _initialize_logging(self) -> None:
        """Set up the application-wide logging system (REQ-HS-013)."""
        initialize_logging(log_dir=_APP_DATA_DIR / "logs")

    def _check_roles(self) -> RoleManager:
        """Resolve the current user's role (REQ-HS-009).

        Returns
        -------
        RoleManager
            Initialised role manager.
        """
        return RoleManager(config_dir=_APP_DATA_DIR / "config")

    def _get_user_config_root(self) -> Path:
        """Determine the user profile config directory root.

        Returns
        -------
            Path to the user config directory (``~/.vi_toolbox/config``).
        """
        return Path.home() / ".vi_toolbox" / "config"

    def _initialize_config(self) -> ConfigManager:
        """Initialise per-tool configuration management (REQ-HS-006).

        Returns
        -------
        ConfigManager
            Initialised config manager.
        """
        return ConfigManager(config_dir=_APP_DATA_DIR / "config")

    def _validate_bundled_configs(self) -> None:
        """Validate that bundled configs exist (warn if missing).

        Bundled configs are loaded from the embedded module (frozen) or
        the dev JSON files (source).  A missing or empty set indicates a
        corrupted or incomplete bundle.
        """
        from app.core.resources import load_bundled_pipeline_configs

        bundled = load_bundled_pipeline_configs()
        if not bundled:
            _log.warning("No bundled pipeline configs found.")
            return

        _log.info("Found %d bundled pipeline config(s)", len(bundled))

    def _create_main_window(
        self,
        tool_registry: ToolRegistry,
        role_manager: RoleManager,
        config_manager: ConfigManager,
        layout_persistence: LayoutPersistence,
        user_config_dir: Path,
    ) -> MainWindow:
        """Instantiate and return the main application window.

        Parameters
        ----------
        tool_registry : ToolRegistry
            Shared registry instance.
        role_manager : RoleManager
            Initialised role manager.
        config_manager : ConfigManager
            Initialised config manager.
        layout_persistence : LayoutPersistence
            Layout state handler.
        user_config_dir : Path
            User profile config directory.

        Returns
        -------
        MainWindow
            Ready-to-show main window.
        """
        return MainWindow(
            tool_registry=tool_registry,
            role_manager=role_manager,
            config_manager=config_manager,
            layout_persistence=layout_persistence,
            user_config_dir=user_config_dir,
        )
