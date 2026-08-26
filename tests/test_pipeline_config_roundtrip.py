"""Tests that SCIBIT pipeline configurations survive a save → load roundtrip.

The SCIBIT pipeline configuration (Spec §3.7 / §5) is the central
artefact that decouples calibration from per-pipeline tuning: it carries
the pipeline variant, pipeline-level options, and per-stage operator
assignments plus parameter values. A user-saved configuration must
reload **identically** so that calibration starts from the exact state
the user last confirmed.

Two layers are exercised:

* :class:`~app.tools.scibit.config.config.Configuration` —
  :meth:`save`/`load` against a known file path.
* :class:`~app.tools.scibit.config.config.PipelineConfigStore` — the
  directory-backed store used in production for the user's saved
  configurations.

Covers REQ-HS-006 (per-tool configuration) and REQ-T1-019 (loading a
complete pipeline configuration from a JSON file).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.tools.scibit.config.config import (
    Configuration,
    PipelineConfigStore,
    PipelineOptions,
    StageConfig,
)
from app.tools.scibit.core.types import DebugExportMode


def _build_sample_configuration(name: str = "test_config") -> Configuration:
    """Return a Configuration with non-trivial values across every layer.

    Touches all four payload areas so a roundtrip regression is hard to
    miss: pipeline variant id, pipeline options (all four fields), and
    multiple stage configs (both built-in stages with empty operator and
    operator-driven stages with rich parameter dicts).
    """
    return Configuration(
        pipeline="direct_roi",
        pipeline_options=PipelineOptions(
            identifier_pattern_preset="Two uppercase letters + 2 digits",
            manual_confirmation_required=True,
            confidence_threshold_percent=92.5,
            debug_export_mode=DebugExportMode.CALIBRATION,
        ),
        stages={
            "calibration_setup": StageConfig(
                operator="",
                parameters={
                    "rotation_degrees": -90.0,
                    "invert_colors": True,
                    "downscale_factor": 30,
                },
            ),
            "identifier_region_selection": StageConfig(
                operator="",
                parameters={"roi_tolerance_margin": 15},
            ),
            "roi_preprocess": StageConfig(
                operator="OpenCVOperator",
                parameters={
                    "clahe_enabled": True,
                    "clahe_clip_limit": 6.0,
                    "clahe_tile_grid_size": 1,
                    "adaptive_threshold_enabled": False,
                    "adaptive_threshold_method": "GAUSSIAN",
                    "adaptive_threshold_block_size": 11,
                    "adaptive_threshold_c": 2,
                    "adaptive_threshold_invert": False,
                },
            ),
            "text_recognition": StageConfig(
                operator="PaddleOCROperator",
                parameters={},
            ),
            "validation": StageConfig(operator="", parameters={}),
        },
        name=name,
    )


# ---------------------------------------------------------------------------
# Configuration.save / Configuration.load
# ---------------------------------------------------------------------------


class TestConfigurationRoundtrip:
    """``Configuration.save → Configuration.load`` preserves every field."""

    def test_save_then_load_equal_object(self, tmp_path: Path) -> None:
        """Loaded configuration compares equal to the original."""
        original = _build_sample_configuration(name="my_config")
        path = tmp_path / "my_config.json"
        original.save(path)
        loaded = Configuration.load(path)
        # Name is derived from the file stem on load, so set it on the
        # original copy too before comparison.
        assert loaded == original

    def test_pipeline_id_preserved(self, tmp_path: Path) -> None:
        """The ``pipeline`` field round-trips unchanged."""
        original = _build_sample_configuration()
        path = tmp_path / "x.json"
        original.save(path)
        assert Configuration.load(path).pipeline == "direct_roi"

    def test_pipeline_options_preserved(self, tmp_path: Path) -> None:
        """Every PipelineOptions field round-trips with its exact value."""
        original = _build_sample_configuration()
        path = tmp_path / "x.json"
        original.save(path)
        loaded = Configuration.load(path)
        assert loaded.pipeline_options == original.pipeline_options
        # Spot-check the enum value (string-encoded in JSON, decoded back).
        assert loaded.pipeline_options.debug_export_mode is DebugExportMode.CALIBRATION

    def test_stage_parameters_preserved(self, tmp_path: Path) -> None:
        """Every stage's operator id and parameter dict survive the trip."""
        original = _build_sample_configuration()
        path = tmp_path / "x.json"
        original.save(path)
        loaded = Configuration.load(path)
        assert set(loaded.stages.keys()) == set(original.stages.keys())
        for stage_name, original_cfg in original.stages.items():
            assert loaded.stages[stage_name] == original_cfg


class TestConfigurationLoadErrors:
    """Malformed and incomplete files raise the documented errors."""

    def test_missing_pipeline_key_raises(self, tmp_path: Path) -> None:
        """Configuration files without the ``pipeline`` field are rejected."""
        path = tmp_path / "broken.json"
        path.write_text('{"pipeline_options": {}, "stages": {}}', encoding="utf-8")
        with pytest.raises(ValueError, match="missing the required 'pipeline' key"):
            Configuration.load(path)

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        """Configuration files with invalid JSON are rejected."""
        path = tmp_path / "bad.json"
        path.write_text("{not really json", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON"):
            Configuration.load(path)


# ---------------------------------------------------------------------------
# PipelineConfigStore — directory-backed CRUD
# ---------------------------------------------------------------------------


class TestPipelineConfigStore:
    """``PipelineConfigStore`` provides list / save / load / delete on a directory."""

    def test_list_empty_directory(self, tmp_path: Path) -> None:
        """A nonexistent or empty directory yields an empty list."""
        store = PipelineConfigStore.from_directories(tmp_path / "deploy", tmp_path / "user")
        assert store.list_configs() == []

    def test_save_and_list(self, tmp_path: Path) -> None:
        """Saved configurations appear under their stem in ``list_configs``."""
        store = PipelineConfigStore.from_directories(tmp_path / "deploy", tmp_path / "user")
        store.save_config(_build_sample_configuration(name="alpha"))
        store.save_config(_build_sample_configuration(name="bravo"))
        assert store.list_configs() == ["alpha", "bravo"]

    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        """``load_config`` returns a Configuration equal to the saved one."""
        store = PipelineConfigStore.from_directories(tmp_path / "deploy", tmp_path / "user")
        original = _build_sample_configuration(name="alpha")
        store.save_config(original)
        loaded = store.load_config("alpha")
        assert loaded == original

    def test_delete_removes_file_and_returns_true(self, tmp_path: Path) -> None:
        """``delete_config`` removes the file and reports success."""
        store = PipelineConfigStore.from_directories(tmp_path / "deploy", tmp_path / "user")
        store.save_config(_build_sample_configuration(name="alpha"))
        assert store.delete_config("alpha") is True
        assert not store.config_exists("alpha")
        assert store.list_configs() == []

    def test_delete_unknown_returns_false(self, tmp_path: Path) -> None:
        """Deleting a missing configuration is a no-op returning ``False``."""
        store = PipelineConfigStore.from_directories(tmp_path / "deploy", tmp_path / "user")
        assert store.delete_config("does_not_exist") is False

    def test_load_unknown_raises(self, tmp_path: Path) -> None:
        """``load_config`` raises FileNotFoundError for an unknown name."""
        store = PipelineConfigStore.from_directories(tmp_path / "deploy", tmp_path / "user")
        with pytest.raises(FileNotFoundError):
            store.load_config("missing")


# ---------------------------------------------------------------------------
# PipelineConfigStore — bundled vs user override behaviour
# ---------------------------------------------------------------------------


class TestPipelineConfigStoreBundled:
    """Bundled (embedded) configs are read-only; user files override them."""

    def test_bundled_config_listed_and_loaded(self, tmp_path: Path) -> None:
        """A config in the deployment dir appears in the list and loads."""
        deploy = tmp_path / "deploy"
        deploy.mkdir()
        bundled = _build_sample_configuration(name="GPD")
        bundled.save(deploy / "GPD.json")

        store = PipelineConfigStore.from_directories(deploy, tmp_path / "user")

        assert "GPD" in store.list_configs()
        assert store.is_bundled_config("GPD") is True
        loaded = store.load_config("GPD")
        assert loaded.pipeline == bundled.pipeline

    def test_user_override_takes_precedence(self, tmp_path: Path) -> None:
        """A user file with the same name shadows the bundled config on load.

        ``is_bundled_config`` still reports ``True`` (membership-only
        check), but ``load_config`` returns the user version by default.
        Pass ``bundled=True`` to load the bundled copy.
        """
        deploy = tmp_path / "deploy"
        deploy.mkdir()
        user = tmp_path / "user"
        user.mkdir()

        bundled = _build_sample_configuration(name="GPD")
        bundled.save(deploy / "GPD.json")

        override = Configuration(
            pipeline="direct_roi",
            pipeline_options=PipelineOptions(),
            stages={},
            name="GPD",
        )
        override.save(user / "GPD.json")

        store = PipelineConfigStore.from_directories(deploy, user)

        assert "GPD" in store.list_configs()
        assert store.is_bundled_config("GPD") is True
        # Default load returns the user override.
        loaded = store.load_config("GPD")
        assert loaded == override
        # Explicit bundled=True returns the bundled copy.
        loaded_bundled = store.load_config("GPD", bundled=True)
        assert loaded_bundled == bundled

    def test_list_config_entries_separates_bundled_and_user(self, tmp_path: Path) -> None:
        """``list_config_entries`` lists both versions of a same-name config."""
        deploy = tmp_path / "deploy"
        deploy.mkdir()
        user = tmp_path / "user"
        user.mkdir()

        bundled = _build_sample_configuration(name="GPD")
        bundled.save(deploy / "GPD.json")
        user_cfg = _build_sample_configuration(name="custom")
        store = PipelineConfigStore.from_directories(deploy, user)
        store.save_config(user_cfg)

        entries = store.list_config_entries()
        assert ("GPD", True) in entries
        assert ("custom", False) in entries

    def test_list_config_entries_dual_entry_for_same_name(self, tmp_path: Path) -> None:
        """Both bundled and user entries appear when names collide."""
        deploy = tmp_path / "deploy"
        deploy.mkdir()
        user = tmp_path / "user"
        user.mkdir()

        bundled = _build_sample_configuration(name="GPD")
        bundled.save(deploy / "GPD.json")
        store = PipelineConfigStore.from_directories(deploy, user)
        store.save_config(_build_sample_configuration(name="GPD"))

        entries = store.list_config_entries()
        assert entries.count(("GPD", True)) == 1
        assert entries.count(("GPD", False)) == 1

    def test_load_config_bundled_flag(self, tmp_path: Path) -> None:
        """``load_config(bundled=True)`` loads bundled even with user override."""
        deploy = tmp_path / "deploy"
        deploy.mkdir()
        user = tmp_path / "user"
        user.mkdir()

        bundled = _build_sample_configuration(name="GPD")
        bundled.save(deploy / "GPD.json")
        override = Configuration(
            pipeline="direct_roi",
            pipeline_options=PipelineOptions(),
            stages={},
            name="GPD",
        )
        override.save(user / "GPD.json")

        store = PipelineConfigStore.from_directories(deploy, user)

        assert store.load_config("GPD", bundled=True) == bundled
        assert store.load_config("GPD", bundled=False) == override
        # Default is bundled=False (user precedence).
        assert store.load_config("GPD") == override

    def test_is_bundled_false_for_user_only(self, tmp_path: Path) -> None:
        """``is_bundled_config`` is False for a user-only config."""
        store = PipelineConfigStore.from_directories(tmp_path / "deploy", tmp_path / "user")
        store.save_config(_build_sample_configuration(name="custom"))
        assert store.is_bundled_config("custom") is False
