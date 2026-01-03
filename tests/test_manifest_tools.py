"""Tests for manifest tools."""

import json
import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.manifest_tools.validator import ManifestValidator
from src.manifest_tools.merger import ManifestMerger


class TestManifestValidator:
    """Tests for ManifestValidator."""

    def test_valid_manifest(self, sample_manifest):
        """Test validation of a valid manifest."""
        validator = ManifestValidator()
        assert validator.validate(sample_manifest) is True
        assert len(validator.errors) == 0

    def test_missing_required_field(self, sample_manifest):
        """Test validation fails when required field is missing."""
        validator = ManifestValidator()
        
        # Remove required field
        del sample_manifest["host_id"]
        
        assert validator.validate(sample_manifest) is False
        assert any("host_id" in e for e in validator.errors)

    def test_invalid_os_major(self, sample_manifest):
        """Test validation fails for invalid OS major version."""
        validator = ManifestValidator()
        
        sample_manifest["os"]["major"] = 7
        
        assert validator.validate(sample_manifest) is False
        assert any("OS major version" in e for e in validator.errors)

    def test_invalid_arch(self, sample_manifest):
        """Test validation fails for invalid architecture."""
        validator = ManifestValidator()
        
        sample_manifest["arch"] = "ppc64le"
        
        assert validator.validate(sample_manifest) is False
        assert any("architecture" in e for e in validator.errors)

    def test_empty_rpms_warning(self, sample_manifest):
        """Test validation warns on empty RPM list."""
        validator = ManifestValidator()
        
        sample_manifest["installed_rpms"] = []
        
        # Should still validate but with warning
        validator.validate(sample_manifest)
        assert any("empty" in w for w in validator.warnings)

    def test_validate_file(self, tmp_path, sample_manifest):
        """Test file validation."""
        validator = ManifestValidator()
        
        manifest_file = tmp_path / "test.json"
        with open(manifest_file, "w") as f:
            json.dump(sample_manifest, f)
        
        assert validator.validate_file(manifest_file) is True

    def test_validate_invalid_json(self, tmp_path):
        """Test validation fails for invalid JSON."""
        validator = ManifestValidator()
        
        bad_file = tmp_path / "bad.json"
        with open(bad_file, "w") as f:
            f.write("not valid json")
        
        assert validator.validate_file(bad_file) is False
        assert any("Invalid JSON" in e for e in validator.errors)

    def test_validate_missing_file(self, tmp_path):
        """Test validation fails for missing file."""
        validator = ManifestValidator()
        
        assert validator.validate_file(tmp_path / "nonexistent.json") is False
        assert any("not found" in e for e in validator.errors)


class TestManifestMerger:
    """Tests for ManifestMerger."""

    def test_merge_single_manifest(self, tmp_path, sample_manifest):
        """Test merging a single manifest."""
        merger = ManifestMerger(os_major=9)
        
        manifest_file = tmp_path / "test.json"
        with open(manifest_file, "w") as f:
            json.dump(sample_manifest, f)
        
        result = merger.add_manifest(manifest_file)
        assert result is True
        assert len(merger.manifests) == 1

    def test_merge_wrong_os_version(self, tmp_path, sample_manifest_rhel8):
        """Test that wrong OS version manifests are rejected."""
        merger = ManifestMerger(os_major=9)
        
        manifest_file = tmp_path / "rhel8.json"
        with open(manifest_file, "w") as f:
            json.dump(sample_manifest_rhel8, f)
        
        result = merger.add_manifest(manifest_file)
        assert result is False
        assert len(merger.manifests) == 0

    def test_merge_from_directory(self, manifest_dir):
        """Test merging from directory."""
        merger = ManifestMerger(os_major=9)
        count = merger.add_manifests_from_directory(manifest_dir)
        
        # Should only add RHEL 9 manifest
        assert count == 1
        assert len(merger.manifests) == 1

    def test_get_merged_installed_rpms(self, tmp_path, sample_manifest):
        """Test getting merged RPM list."""
        merger = ManifestMerger(os_major=9)
        
        manifest_file = tmp_path / "test.json"
        with open(manifest_file, "w") as f:
            json.dump(sample_manifest, f)
        
        merger.add_manifest(manifest_file)
        merged = merger.get_merged_installed_rpms()
        
        assert "bash" in merged
        assert "kernel" in merged
        assert "openssl" in merged

    def test_get_host_summary(self, tmp_path, sample_manifest):
        """Test getting host summary."""
        merger = ManifestMerger(os_major=9)
        
        manifest_file = tmp_path / "test.json"
        with open(manifest_file, "w") as f:
            json.dump(sample_manifest, f)
        
        merger.add_manifest(manifest_file)
        summary = merger.get_host_summary()
        
        assert len(summary) == 1
        assert summary[0]["host_id"] == "test-host-01"
        assert summary[0]["os_minor"] == 6

    def test_generate_merge_report(self, manifest_dir):
        """Test generating merge report."""
        merger = ManifestMerger(os_major=9)
        merger.add_manifests_from_directory(manifest_dir)
        
        report = merger.generate_merge_report()
        
        assert report["os_major"] == 9
        assert report["manifest_count"] == 1
        assert "unique_packages" in report
        assert "generated_at" in report

    def test_invalid_os_major(self):
        """Test that invalid OS major raises error."""
        with pytest.raises(ValueError):
            ManifestMerger(os_major=7)
