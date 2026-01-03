"""Pytest configuration and fixtures."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def sample_manifest():
    """Return a sample valid manifest."""
    return {
        "schema_version": "1.0",
        "host_id": "test-host-01",
        "os": {
            "name": "Red Hat Enterprise Linux",
            "major": 9,
            "minor": 6,
            "id": "rhel"
        },
        "arch": "x86_64",
        "kernel_version": "5.14.0-427.el9.x86_64",
        "enabled_repos": [
            {"id": "rhel-9-for-x86_64-baseos-rpms", "name": "RHEL 9 BaseOS"},
            {"id": "rhel-9-for-x86_64-appstream-rpms", "name": "RHEL 9 AppStream"}
        ],
        "installed_rpms": [
            {
                "name": "bash",
                "epoch": "0",
                "version": "5.1.8",
                "release": "6.el9",
                "arch": "x86_64",
                "nevra": "bash-5.1.8-6.el9.x86_64"
            },
            {
                "name": "kernel",
                "epoch": "0",
                "version": "5.14.0",
                "release": "427.el9",
                "arch": "x86_64",
                "nevra": "kernel-5.14.0-427.el9.x86_64"
            },
            {
                "name": "openssl",
                "epoch": "1",
                "version": "3.0.7",
                "release": "25.el9",
                "arch": "x86_64",
                "nevra": "openssl-1:3.0.7-25.el9.x86_64"
            }
        ],
        "timestamp": "2024-01-15T12:00:00Z",
        "collector_version": "1.0.0"
    }


@pytest.fixture
def sample_manifest_rhel8():
    """Return a sample RHEL 8 manifest."""
    return {
        "schema_version": "1.0",
        "host_id": "test-host-rhel8",
        "os": {
            "name": "Red Hat Enterprise Linux",
            "major": 8,
            "minor": 10,
            "id": "rhel"
        },
        "arch": "x86_64",
        "kernel_version": "4.18.0-553.el8.x86_64",
        "enabled_repos": [
            {"id": "rhel-8-for-x86_64-baseos-rpms", "name": "RHEL 8 BaseOS"}
        ],
        "installed_rpms": [
            {
                "name": "bash",
                "epoch": "0",
                "version": "4.4.20",
                "release": "4.el8",
                "arch": "x86_64",
                "nevra": "bash-4.4.20-4.el8.x86_64"
            }
        ],
        "timestamp": "2024-01-15T12:00:00Z",
        "collector_version": "1.0.0"
    }


@pytest.fixture
def manifest_dir(tmp_path, sample_manifest, sample_manifest_rhel8):
    """Create a temporary directory with test manifests."""
    manifest_path = tmp_path / "manifests"
    manifest_path.mkdir()
    
    # Write RHEL 9 manifest
    with open(manifest_path / "test-host-01-manifest.json", "w") as f:
        json.dump(sample_manifest, f)
    
    # Write RHEL 8 manifest
    with open(manifest_path / "test-host-rhel8-manifest.json", "w") as f:
        json.dump(sample_manifest_rhel8, f)
    
    return manifest_path
