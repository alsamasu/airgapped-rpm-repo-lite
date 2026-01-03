"""Tests for bundle builder components."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.bundle_builder.resolver import DependencyResolver, ResolvedPackage
from src.bundle_builder.downloader import RPMDownloader


class TestResolvedPackage:
    """Tests for ResolvedPackage dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        pkg = ResolvedPackage(
            name="bash",
            epoch="0",
            version="5.1.8",
            release="6.el9",
            arch="x86_64",
            nevra="bash-5.1.8-6.el9.x86_64",
            repo_id="rhel-9-baseos",
            package_type="update",
            size_bytes=1234567,
            advisory_id="RHSA-2024:1234",
            required_by=["host1", "host2"]
        )
        
        d = pkg.to_dict()
        
        assert d["name"] == "bash"
        assert d["type"] == "update"
        assert d["advisory_id"] == "RHSA-2024:1234"
        assert len(d["required_by"]) == 2


class TestDependencyResolver:
    """Tests for DependencyResolver."""

    def test_init(self):
        """Test resolver initialization."""
        packages = ["bash", "kernel", "openssl"]
        resolver = DependencyResolver(packages)
        
        assert len(resolver.installed_packages) == 3
        assert resolver.prefer_security is True

    def test_init_without_security_preference(self):
        """Test resolver without security preference."""
        resolver = DependencyResolver(["bash"], prefer_security=False)
        
        assert resolver.prefer_security is False

    @patch("subprocess.run")
    def test_get_available_updates_empty(self, mock_run):
        """Test when no updates are available."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr=""
        )
        
        resolver = DependencyResolver(["bash"])
        updates = resolver._get_available_updates()
        
        assert len(updates) == 0

    @patch("subprocess.run")
    def test_get_available_updates_found(self, mock_run):
        """Test when updates are available."""
        mock_run.return_value = MagicMock(
            returncode=100,
            stdout="bash.x86_64    5.1.8-7.el9    rhel-9-baseos\nkernel.x86_64  5.14.0-428.el9 rhel-9-baseos\n",
            stderr=""
        )
        
        resolver = DependencyResolver(["bash", "kernel"])
        updates = resolver._get_available_updates()
        
        assert "bash" in updates
        assert "kernel" in updates


class TestRPMDownloader:
    """Tests for RPMDownloader."""

    def test_init_creates_directory(self, tmp_path):
        """Test that init creates download directory."""
        download_dir = tmp_path / "downloads"
        downloader = RPMDownloader(download_dir)
        
        assert download_dir.exists()

    def test_compute_sha256(self, tmp_path):
        """Test SHA256 computation."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")
        
        downloader = RPMDownloader(tmp_path)
        sha256 = downloader._compute_sha256(test_file)
        
        # Known SHA256 of "test content"
        assert sha256 == "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72"

    def test_get_successful_downloads(self, tmp_path):
        """Test filtering successful downloads."""
        downloader = RPMDownloader(tmp_path)
        
        pkg = ResolvedPackage(
            name="test",
            epoch="0",
            version="1.0",
            release="1",
            arch="x86_64",
            nevra="test-1.0-1.x86_64",
            repo_id="test",
            package_type="update"
        )
        
        from src.bundle_builder.downloader import DownloadResult
        
        downloader.results = [
            DownloadResult(pkg, True, tmp_path / "test.rpm", "abc123", None),
            DownloadResult(pkg, False, None, None, "Failed"),
        ]
        
        successful = downloader.get_successful_downloads()
        assert len(successful) == 1

    def test_get_failed_downloads(self, tmp_path):
        """Test filtering failed downloads."""
        downloader = RPMDownloader(tmp_path)
        
        pkg = ResolvedPackage(
            name="test",
            epoch="0",
            version="1.0",
            release="1",
            arch="x86_64",
            nevra="test-1.0-1.x86_64",
            repo_id="test",
            package_type="update"
        )
        
        from src.bundle_builder.downloader import DownloadResult
        
        downloader.results = [
            DownloadResult(pkg, True, tmp_path / "test.rpm", "abc123", None),
            DownloadResult(pkg, False, None, None, "Failed"),
        ]
        
        failed = downloader.get_failed_downloads()
        assert len(failed) == 1

    def test_generate_checksums_file(self, tmp_path):
        """Test checksums file generation."""
        # Create a test RPM file
        rpm_file = tmp_path / "test-1.0-1.x86_64.rpm"
        rpm_file.write_text("fake rpm content")
        
        downloader = RPMDownloader(tmp_path)
        
        pkg = ResolvedPackage(
            name="test",
            epoch="0",
            version="1.0",
            release="1",
            arch="x86_64",
            nevra="test-1.0-1.x86_64",
            repo_id="test",
            package_type="update"
        )
        
        from src.bundle_builder.downloader import DownloadResult
        
        sha256 = downloader._compute_sha256(rpm_file)
        downloader.results = [
            DownloadResult(pkg, True, rpm_file, sha256, None),
        ]
        
        checksums_path = downloader.generate_checksums_file()
        
        assert checksums_path.exists()
        content = checksums_path.read_text()
        assert sha256 in content
        assert "test-1.0-1.x86_64.rpm" in content
