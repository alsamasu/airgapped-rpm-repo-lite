#!/usr/bin/env python3
"""
Manifest collector for Policy B installed-package closure.

Collects installed RPM information from a host and generates
a canonical manifest JSON file.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COLLECTOR_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"


class ManifestCollector:
    """Collect host manifest data for Policy B bundle building."""

    def __init__(self, output_dir: str | None = None):
        """Initialize the collector.

        Args:
            output_dir: Directory to write manifest files. Defaults to current directory.
        """
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def collect(self) -> dict[str, Any]:
        """Collect all manifest data from the current host.

        Returns:
            Complete manifest dictionary.
        """
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "host_id": self._get_host_id(),
            "os": self._get_os_info(),
            "arch": self._get_arch(),
            "kernel_version": self._get_kernel_version(),
            "enabled_repos": self._get_enabled_repos(),
            "installed_rpms": self._get_installed_rpms(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "collector_version": COLLECTOR_VERSION,
        }

        # Optionally collect advisory IDs if available
        advisories = self._get_applicable_advisories()
        if advisories:
            manifest["advisory_ids"] = advisories

        return manifest

    def collect_and_save(self, filename: str | None = None) -> Path:
        """Collect manifest and save to JSON file.

        Args:
            filename: Output filename. Defaults to {host_id}-manifest.json.

        Returns:
            Path to the saved manifest file.
        """
        manifest = self.collect()

        if filename is None:
            filename = f"{manifest['host_id']}-manifest.json"

        output_path = self.output_dir / filename
        with open(output_path, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)

        return output_path

    def _get_host_id(self) -> str:
        """Get unique host identifier."""
        # Prefer hostname, fall back to machine-id
        try:
            result = subprocess.run(
                ["hostname", "-f"],
                capture_output=True,
                text=True,
                check=True,
            )
            hostname = result.stdout.strip()
            if hostname:
                return hostname
        except subprocess.CalledProcessError:
            pass

        # Fall back to machine-id
        machine_id_path = Path("/etc/machine-id")
        if machine_id_path.exists():
            return machine_id_path.read_text().strip()[:12]

        # Last resort: short hostname
        try:
            result = subprocess.run(
                ["hostname"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown-host"

    def _get_os_info(self) -> dict[str, Any]:
        """Get OS information from /etc/os-release."""
        os_info = {"name": "Unknown", "major": 0, "minor": 0, "id": "unknown"}

        os_release_path = Path("/etc/os-release")
        if not os_release_path.exists():
            return os_info

        content = os_release_path.read_text()

        # Parse os-release file
        for line in content.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"')

            if key == "NAME":
                os_info["name"] = value
            elif key == "ID":
                os_info["id"] = value
            elif key == "VERSION_ID":
                parts = value.split(".")
                os_info["major"] = int(parts[0])
                if len(parts) > 1:
                    os_info["minor"] = int(parts[1])

        return os_info

    def _get_arch(self) -> str:
        """Get system architecture."""
        try:
            result = subprocess.run(
                ["uname", "-m"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "x86_64"

    def _get_kernel_version(self) -> str:
        """Get current kernel version."""
        try:
            result = subprocess.run(
                ["uname", "-r"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"

    def _get_enabled_repos(self) -> list[dict[str, str]]:
        """Get list of enabled repositories."""
        repos = []

        try:
            result = subprocess.run(
                ["dnf", "repolist", "--enabled", "-v"],
                capture_output=True,
                text=True,
                check=True,
            )

            current_repo: dict[str, str] = {}
            for line in result.stdout.splitlines():
                line = line.strip()

                if line.startswith("Repo-id"):
                    if current_repo:
                        repos.append(current_repo)
                    repo_id = line.split(":", 1)[1].strip()
                    # Remove architecture suffix if present
                    repo_id = re.sub(r"/[a-z0-9_]+$", "", repo_id)
                    current_repo = {"id": repo_id, "name": ""}
                elif line.startswith("Repo-name") and current_repo:
                    current_repo["name"] = line.split(":", 1)[1].strip()
                elif line.startswith("Repo-baseurl") and current_repo:
                    baseurl = line.split(":", 1)[1].strip()
                    if baseurl:
                        current_repo["baseurl"] = baseurl.split()[0]

            if current_repo:
                repos.append(current_repo)

        except subprocess.CalledProcessError:
            # Fall back to simple repolist
            try:
                result = subprocess.run(
                    ["dnf", "repolist", "--enabled"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                for line in result.stdout.splitlines()[1:]:  # Skip header
                    parts = line.split(None, 1)
                    if len(parts) >= 2:
                        repos.append({"id": parts[0], "name": parts[1].strip()})
            except subprocess.CalledProcessError:
                pass

        return repos

    def _get_installed_rpms(self) -> list[dict[str, str]]:
        """Get list of all installed RPMs in NEVRA format."""
        rpms = []

        try:
            # Use rpm to get exact NEVRA information
            result = subprocess.run(
                [
                    "rpm",
                    "-qa",
                    "--queryformat",
                    "%{NAME}\\t%{EPOCH}\\t%{VERSION}\\t%{RELEASE}\\t%{ARCH}\\n",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            for line in result.stdout.splitlines():
                if not line.strip():
                    continue

                parts = line.split("\t")
                if len(parts) != 5:
                    continue

                name, epoch, version, release, arch = parts

                # Handle (none) epoch
                if epoch == "(none)":
                    epoch = "0"

                # Build NEVRA string
                if epoch != "0":
                    nevra = f"{name}-{epoch}:{version}-{release}.{arch}"
                else:
                    nevra = f"{name}-{version}-{release}.{arch}"

                rpms.append(
                    {
                        "name": name,
                        "epoch": epoch,
                        "version": version,
                        "release": release,
                        "arch": arch,
                        "nevra": nevra,
                    }
                )

        except subprocess.CalledProcessError as e:
            print(f"Error collecting RPM list: {e}", file=sys.stderr)

        return sorted(rpms, key=lambda x: x["name"])

    def _get_applicable_advisories(self) -> list[str]:
        """Get list of applicable security advisories (if available)."""
        advisories = []

        try:
            result = subprocess.run(
                ["dnf", "updateinfo", "list", "--security", "--available"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    # Parse advisory IDs (RHSA, RHBA, RHEA format)
                    match = re.match(r"^(RH[SBAE]A-\d{4}:\d+)", line)
                    if match:
                        advisory_id = match.group(1)
                        if advisory_id not in advisories:
                            advisories.append(advisory_id)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # Advisory collection is optional, don't fail if it doesn't work
            pass

        return sorted(advisories)


def main():
    """CLI entry point for manifest collection."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Collect RPM manifest for Policy B bundle building"
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=".",
        help="Output directory for manifest file (default: current directory)",
    )
    parser.add_argument(
        "-f",
        "--filename",
        help="Output filename (default: {host_id}-manifest.json)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print manifest to stdout instead of file",
    )

    args = parser.parse_args()

    collector = ManifestCollector(output_dir=args.output_dir)

    if args.stdout:
        manifest = collector.collect()
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        output_path = collector.collect_and_save(filename=args.filename)
        print(f"Manifest written to: {output_path}")


if __name__ == "__main__":
    main()
