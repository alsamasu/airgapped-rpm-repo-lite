#!/usr/bin/env python3
"""
Manifest validator for Policy B installed-package closure.

Validates manifest files against the canonical schema.
"""

import json
import sys
from pathlib import Path
from typing import Any


class ManifestValidator:
    """Validate host manifests against the schema."""

    REQUIRED_FIELDS = [
        "schema_version",
        "host_id",
        "os",
        "arch",
        "enabled_repos",
        "installed_rpms",
        "timestamp",
    ]

    REQUIRED_OS_FIELDS = ["major", "minor", "name"]
    REQUIRED_RPM_FIELDS = ["name", "epoch", "version", "release", "arch"]
    VALID_ARCHES = ["x86_64", "aarch64", "noarch", "i686"]
    VALID_OS_MAJORS = [8, 9]

    def __init__(self):
        """Initialize the validator."""
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate(self, manifest: dict[str, Any]) -> bool:
        """Validate a manifest dictionary.

        Args:
            manifest: Manifest dictionary to validate.

        Returns:
            True if valid, False otherwise.
        """
        self.errors = []
        self.warnings = []

        self._validate_required_fields(manifest)
        self._validate_schema_version(manifest)
        self._validate_os(manifest)
        self._validate_arch(manifest)
        self._validate_repos(manifest)
        self._validate_rpms(manifest)
        self._validate_timestamp(manifest)

        return len(self.errors) == 0

    def validate_file(self, filepath: str | Path) -> bool:
        """Validate a manifest JSON file.

        Args:
            filepath: Path to manifest file.

        Returns:
            True if valid, False otherwise.
        """
        path = Path(filepath)

        if not path.exists():
            self.errors = [f"File not found: {path}"]
            return False

        try:
            with open(path) as f:
                manifest = json.load(f)
        except json.JSONDecodeError as e:
            self.errors = [f"Invalid JSON: {e}"]
            return False

        return self.validate(manifest)

    def _validate_required_fields(self, manifest: dict[str, Any]) -> None:
        """Check for required top-level fields."""
        for field in self.REQUIRED_FIELDS:
            if field not in manifest:
                self.errors.append(f"Missing required field: {field}")

    def _validate_schema_version(self, manifest: dict[str, Any]) -> None:
        """Validate schema version."""
        version = manifest.get("schema_version")
        if version and version != "1.0":
            self.warnings.append(
                f"Unknown schema version: {version} (expected 1.0)"
            )

    def _validate_os(self, manifest: dict[str, Any]) -> None:
        """Validate OS information."""
        os_info = manifest.get("os", {})

        for field in self.REQUIRED_OS_FIELDS:
            if field not in os_info:
                self.errors.append(f"Missing required os field: {field}")

        major = os_info.get("major")
        if major is not None and major not in self.VALID_OS_MAJORS:
            self.errors.append(
                f"Invalid OS major version: {major} (expected 8 or 9)"
            )

        minor = os_info.get("minor")
        if minor is not None and not isinstance(minor, int):
            self.errors.append(f"OS minor version must be integer, got: {type(minor)}")

    def _validate_arch(self, manifest: dict[str, Any]) -> None:
        """Validate architecture."""
        arch = manifest.get("arch")
        if arch and arch not in ["x86_64", "aarch64"]:
            self.errors.append(
                f"Invalid system architecture: {arch} (expected x86_64 or aarch64)"
            )

    def _validate_repos(self, manifest: dict[str, Any]) -> None:
        """Validate enabled repositories."""
        repos = manifest.get("enabled_repos", [])

        if not isinstance(repos, list):
            self.errors.append("enabled_repos must be a list")
            return

        for i, repo in enumerate(repos):
            if not isinstance(repo, dict):
                self.errors.append(f"enabled_repos[{i}] must be an object")
                continue

            if "id" not in repo:
                self.errors.append(f"enabled_repos[{i}] missing required field: id")
            if "name" not in repo:
                self.warnings.append(f"enabled_repos[{i}] missing field: name")

    def _validate_rpms(self, manifest: dict[str, Any]) -> None:
        """Validate installed RPMs list."""
        rpms = manifest.get("installed_rpms", [])

        if not isinstance(rpms, list):
            self.errors.append("installed_rpms must be a list")
            return

        if len(rpms) == 0:
            self.warnings.append("installed_rpms is empty")
            return

        # Sample validation (don't validate every single RPM for performance)
        sample_size = min(len(rpms), 100)
        for i in range(sample_size):
            rpm = rpms[i]
            if not isinstance(rpm, dict):
                self.errors.append(f"installed_rpms[{i}] must be an object")
                continue

            for field in self.REQUIRED_RPM_FIELDS:
                if field not in rpm:
                    self.errors.append(
                        f"installed_rpms[{i}] missing required field: {field}"
                    )

            rpm_arch = rpm.get("arch", "")
            if rpm_arch and rpm_arch not in self.VALID_ARCHES:
                self.warnings.append(
                    f"installed_rpms[{i}] has unusual arch: {rpm_arch}"
                )

    def _validate_timestamp(self, manifest: dict[str, Any]) -> None:
        """Validate timestamp format."""
        timestamp = manifest.get("timestamp")
        if not timestamp:
            return

        # Basic ISO 8601 format check
        if not isinstance(timestamp, str):
            self.errors.append("timestamp must be a string")
            return

        # Check for basic datetime format
        if "T" not in timestamp:
            self.errors.append(
                f"timestamp must be ISO 8601 format, got: {timestamp}"
            )

    def get_summary(self) -> str:
        """Get validation summary.

        Returns:
            Human-readable summary string.
        """
        lines = []

        if self.errors:
            lines.append(f"ERRORS ({len(self.errors)}):")
            for error in self.errors:
                lines.append(f"  - {error}")

        if self.warnings:
            lines.append(f"WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                lines.append(f"  - {warning}")

        if not self.errors and not self.warnings:
            lines.append("Manifest is valid.")

        return "\n".join(lines)


def main():
    """CLI entry point for manifest validation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate manifest files against the schema"
    )
    parser.add_argument(
        "manifests",
        nargs="+",
        help="Manifest files to validate",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only output errors",
    )

    args = parser.parse_args()

    validator = ManifestValidator()
    all_valid = True

    for manifest_path in args.manifests:
        is_valid = validator.validate_file(manifest_path)

        if not args.quiet or not is_valid:
            print(f"\n{manifest_path}:")
            print(validator.get_summary())

        if not is_valid:
            all_valid = False

    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
