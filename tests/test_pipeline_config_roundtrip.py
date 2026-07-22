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
        store = PipelineConfigStore(tmp_path / "scibit_configs")
        assert store.list_configs() == []

    def test_save_and_list(self, tmp_path: Path) -> None:
        """Saved configurations appear under their stem in ``list_configs``."""
        store = PipelineConfigStore(tmp_path / "scibit_configs")
        store.save_config(_build_sample_configuration(name="alpha"))
        store.save_config(_build_sample_configuration(name="bravo"))
        assert store.list_configs() == ["alpha", "bravo"]

    def test_save_then_load_roundtrip(self, tmp_path: Path) -> None:
        """``load_config`` returns a Configuration equal to the saved one."""
        store = PipelineConfigStore(tmp_path / "scibit_configs")
        original = _build_sample_configuration(name="alpha")
        store.save_config(original)
        loaded = store.load_config("alpha")
        assert loaded == original

    def test_delete_removes_file_and_returns_true(self, tmp_path: Path) -> None:
        """``delete_config`` removes the file and reports success."""
        store = PipelineConfigStore(tmp_path / "scibit_configs")
        store.save_config(_build_sample_configuration(name="alpha"))
        assert store.delete_config("alpha") is True
        assert not store.config_exists("alpha")
        assert store.list_configs() == []

    def test_delete_unknown_returns_false(self, tmp_path: Path) -> None:
        """Deleting a missing configuration is a no-op returning ``False``."""
        store = PipelineConfigStore(tmp_path / "scibit_configs")
        assert store.delete_config("does_not_exist") is False

    def test_load_unknown_raises(self, tmp_path: Path) -> None:
        """``load_config`` raises FileNotFoundError for an unknown name."""
        store = PipelineConfigStore(tmp_path / "scibit_configs")
        with pytest.raises(FileNotFoundError):
            store.load_config("missing")
