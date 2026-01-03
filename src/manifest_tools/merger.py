#!/usr/bin/env python3
"""
Manifest merger for Policy B installed-package closure.

Merges multiple host manifests into a consolidated view per OS major version.
"""

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ManifestMerger:
    """Merge multiple host manifests for bundle building."""

    def __init__(self, os_major: int):
        """Initialize the merger for a specific OS major version.

        Args:
            os_major: Target OS major version (8 or 9).
        """
        if os_major not in (8, 9):
            raise ValueError(f"OS major version must be 8 or 9, got: {os_major}")

        self.os_major = os_major
        self.manifests: list[dict[str, Any]] = []
        self.manifest_hashes: dict[str, str] = {}

    def add_manifest(self, manifest_path: str | Path) -> bool:
        """Add a manifest file to the merger.

        Args:
            manifest_path: Path to manifest JSON file.

        Returns:
            True if manifest was added (correct OS version), False otherwise.
        """
        path = Path(manifest_path)

        with open(path) as f:
            manifest = json.load(f)

        # Verify OS major version matches
        manifest_os_major = manifest.get("os", {}).get("major")
        if manifest_os_major != self.os_major:
            return False

        # Calculate hash for deduplication and tracking
        manifest_json = json.dumps(manifest, sort_keys=True)
        manifest_hash = hashlib.sha256(manifest_json.encode()).hexdigest()

        host_id = manifest.get("host_id", path.stem)
        self.manifest_hashes[host_id] = f"sha256:{manifest_hash}"
        self.manifests.append(manifest)

        return True

    def add_manifests_from_directory(self, directory: str | Path) -> int:
        """Add all manifest files from a directory.

        Args:
            directory: Directory containing manifest JSON files.

        Returns:
            Number of manifests added.
        """
        directory = Path(directory)
        count = 0

        for manifest_file in directory.glob("*-manifest.json"):
            if self.add_manifest(manifest_file):
                count += 1

        # Also try .json files that might be manifests
        for manifest_file in directory.glob("*.json"):
            if "-manifest" not in manifest_file.name:
                try:
                    if self.add_manifest(manifest_file):
                        count += 1
                except (json.JSONDecodeError, KeyError):
                    continue

        return count

    def get_merged_installed_rpms(self) -> dict[str, set[str]]:
        """Get union of all installed RPMs across all hosts.

        Returns:
            Dictionary mapping package name to set of NEVRAs seen.
        """
        all_packages: dict[str, set[str]] = defaultdict(set)

        for manifest in self.manifests:
            for rpm in manifest.get("installed_rpms", []):
                name = rpm.get("name", "")
                nevra = rpm.get("nevra", "")
                if name and nevra:
                    all_packages[name].add(nevra)

        return dict(all_packages)

    def get_package_to_hosts_map(self) -> dict[str, list[str]]:
        """Get mapping of package names to host IDs that have them installed.

        Returns:
            Dictionary mapping package name to list of host IDs.
        """
        package_hosts: dict[str, list[str]] = defaultdict(list)

        for manifest in self.manifests:
            host_id = manifest.get("host_id", "unknown")
            for rpm in manifest.get("installed_rpms", []):
                name = rpm.get("name", "")
                if name:
                    package_hosts[name].append(host_id)

        return dict(package_hosts)

    def get_enabled_repos_union(self) -> list[dict[str, str]]:
        """Get union of all enabled repositories across hosts.

        Returns:
            List of unique repositories.
        """
        repos_seen: dict[str, dict[str, str]] = {}

        for manifest in self.manifests:
            for repo in manifest.get("enabled_repos", []):
                repo_id = repo.get("id", "")
                if repo_id and repo_id not in repos_seen:
                    repos_seen[repo_id] = repo

        return list(repos_seen.values())

    def get_host_summary(self) -> list[dict[str, Any]]:
        """Get summary information for all hosts in the merge.

        Returns:
            List of host summaries.
        """
        summaries = []

        for manifest in self.manifests:
            host_id = manifest.get("host_id", "unknown")
            summaries.append(
                {
                    "host_id": host_id,
                    "manifest_hash": self.manifest_hashes.get(host_id, ""),
                    "os_minor": manifest.get("os", {}).get("minor", 0),
                    "arch": manifest.get("arch", "x86_64"),
                    "installed_count": len(manifest.get("installed_rpms", [])),
                    "timestamp": manifest.get("timestamp", ""),
                }
            )

        return summaries

    def generate_merge_report(self) -> dict[str, Any]:
        """Generate a complete merge report.

        Returns:
            Merge report dictionary.
        """
        merged_rpms = self.get_merged_installed_rpms()
        package_hosts = self.get_package_to_hosts_map()

        return {
            "os_major": self.os_major,
            "manifest_count": len(self.manifests),
            "hosts": self.get_host_summary(),
            "unique_packages": len(merged_rpms),
            "total_package_instances": sum(len(hosts) for hosts in package_hosts.values()),
            "enabled_repos": self.get_enabled_repos_union(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def export_package_list(self, output_path: str | Path) -> Path:
        """Export the merged package list to a file.

        Args:
            output_path: Output file path.

        Returns:
            Path to the exported file.
        """
        path = Path(output_path)
        merged_rpms = self.get_merged_installed_rpms()

        # Create a sorted list of unique package names
        packages = sorted(merged_rpms.keys())

        with open(path, "w") as f:
            for package in packages:
                f.write(f"{package}\n")

        return path


def main():
    """CLI entry point for manifest merging."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Merge host manifests for Policy B bundle building"
    )
    parser.add_argument(
        "manifests",
        nargs="+",
        help="Manifest files or directories to merge",
    )
    parser.add_argument(
        "--os-major",
        type=int,
        required=True,
        choices=[8, 9],
        help="Target OS major version",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file for merge report",
    )
    parser.add_argument(
        "--package-list",
        help="Output file for merged package list",
    )

    args = parser.parse_args()

    merger = ManifestMerger(os_major=args.os_major)

    for manifest_path in args.manifests:
        path = Path(manifest_path)
        if path.is_dir():
            count = merger.add_manifests_from_directory(path)
            print(f"Added {count} manifests from {path}")
        elif path.is_file():
            if merger.add_manifest(path):
                print(f"Added manifest: {path}")
            else:
                print(f"Skipped (wrong OS version): {path}")

    report = merger.generate_merge_report()
    report_json = json.dumps(report, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report_json)
        print(f"Merge report written to: {args.output}")
    else:
        print(report_json)

    if args.package_list:
        merger.export_package_list(args.package_list)
        print(f"Package list written to: {args.package_list}")


if __name__ == "__main__":
    main()
