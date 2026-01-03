#!/usr/bin/env python3
"""
Bundle builder for Policy B installed-package closure.

Creates self-contained repository bundles with RPMs and repodata.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .resolver import DependencyResolver
from .downloader import RPMDownloader


class BundleBuilder:
    """Build self-contained RPM bundles."""

    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        os_major: int,
        manifest_dir: str | Path,
        output_dir: str | Path,
        work_dir: str | Path | None = None,
    ):
        """Initialize the bundle builder.

        Args:
            os_major: Target OS major version (8 or 9).
            manifest_dir: Directory containing host manifests.
            output_dir: Directory for final bundle output.
            work_dir: Working directory for intermediate files.
        """
        if os_major not in (8, 9):
            raise ValueError(f"OS major must be 8 or 9, got: {os_major}")

        self.os_major = os_major
        self.manifest_dir = Path(manifest_dir)
        self.output_dir = Path(output_dir)
        self.work_dir = Path(work_dir) if work_dir else Path("/tmp/bundle-build")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.bundle_id = ""
        self.build_log: list[str] = []
        self.metadata: dict[str, Any] = {}

    def build(self) -> Path:
        """Execute the full bundle build process.

        Returns:
            Path to the final bundle archive.
        """
        timestamp = datetime.now(timezone.utc)
        self.bundle_id = f"bundle-rhel{self.os_major}-{timestamp.strftime('%Y%m%dT%H%M%SZ')}"

        self._log(f"Starting bundle build: {self.bundle_id}")

        # Setup work directories
        bundle_work_dir = self.work_dir / self.bundle_id
        rpms_dir = bundle_work_dir / "rpms"
        repodata_dir = bundle_work_dir / "repodata"
        manifests_copy_dir = bundle_work_dir / "manifests"

        rpms_dir.mkdir(parents=True, exist_ok=True)
        manifests_copy_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Step 1: Load and merge manifests
            self._log("Step 1: Loading manifests")
            from ..manifest_tools.merger import ManifestMerger

            merger = ManifestMerger(os_major=self.os_major)
            manifest_count = merger.add_manifests_from_directory(self.manifest_dir)
            self._log(f"  Loaded {manifest_count} manifests")

            if manifest_count == 0:
                raise RuntimeError(f"No RHEL {self.os_major} manifests found")

            # Copy manifests to bundle
            for manifest_file in self.manifest_dir.glob("*.json"):
                shutil.copy2(manifest_file, manifests_copy_dir)

            # Step 2: Get merged package list
            self._log("Step 2: Merging installed packages")
            merged_rpms = merger.get_merged_installed_rpms()
            package_names = list(merged_rpms.keys())
            self._log(f"  Found {len(package_names)} unique packages")

            # Step 3: Resolve updates and dependencies
            self._log("Step 3: Resolving updates and dependencies")
            resolver = DependencyResolver(package_names, prefer_security=True)
            resolved = resolver.resolve()
            self._log(f"  Resolved {len(resolved)} packages")

            if resolver.errors:
                for error in resolver.errors:
                    self._log(f"  Warning: {error}")

            if not resolved:
                self._log("  No updates available - creating empty bundle")

            # Step 4: Download RPMs
            self._log("Step 4: Downloading RPMs")
            downloader = RPMDownloader(rpms_dir)

            if resolved:
                results = downloader.download_packages(resolved)
                success_count = len(downloader.get_successful_downloads())
                fail_count = len(downloader.get_failed_downloads())
                self._log(f"  Downloaded: {success_count}, Failed: {fail_count}")

                for failed in downloader.get_failed_downloads():
                    self._log(f"  Failed: {failed.package.name} - {failed.error}")

            # Step 5: Generate repodata
            self._log("Step 5: Generating repodata")
            self._generate_repodata(rpms_dir)
            self._log("  Repodata generated")

            # Step 6: Generate checksums
            self._log("Step 6: Generating checksums")
            downloader.generate_checksums_file(bundle_work_dir / "SHA256SUMS")

            # Step 7: Build metadata
            self._log("Step 7: Building metadata")
            self.metadata = self._build_metadata(
                timestamp=timestamp,
                merger=merger,
                resolved=resolved,
                downloader=downloader,
            )
            metadata_path = bundle_work_dir / "metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(self.metadata, f, indent=2)
            self._log("  Metadata written")

            # Step 8: Write build log
            self._log("Step 8: Finalizing")
            log_path = bundle_work_dir / "build.log"
            with open(log_path, "w") as f:
                f.write("\n".join(self.build_log) + "\n")

            # Step 9: Create archive
            self._log("Step 9: Creating archive")
            archive_path = self._create_archive(bundle_work_dir)
            self._log(f"  Bundle created: {archive_path}")

            # Compute final bundle hash
            bundle_hash = self._compute_file_hash(archive_path)
            self._log(f"  SHA256: {bundle_hash}")

            return archive_path

        except Exception as e:
            self._log(f"ERROR: {e}")
            raise

        finally:
            # Cleanup work directory
            if bundle_work_dir.exists():
                shutil.rmtree(bundle_work_dir, ignore_errors=True)

    def _log(self, message: str) -> None:
        """Add message to build log.

        Args:
            message: Log message.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        log_entry = f"[{timestamp}] {message}"
        self.build_log.append(log_entry)
        print(log_entry)

    def _generate_repodata(self, rpms_dir: Path) -> None:
        """Generate repository metadata using createrepo_c.

        Args:
            rpms_dir: Directory containing RPMs.
        """
        try:
            subprocess.run(
                ["createrepo_c", "--update", str(rpms_dir)],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            # Fall back to createrepo if createrepo_c not available
            subprocess.run(
                ["createrepo", "--update", str(rpms_dir)],
                check=True,
                capture_output=True,
            )

    def _build_metadata(
        self,
        timestamp: datetime,
        merger: Any,
        resolved: list,
        downloader: RPMDownloader,
    ) -> dict[str, Any]:
        """Build bundle metadata.

        Args:
            timestamp: Build timestamp.
            merger: ManifestMerger instance.
            resolved: List of resolved packages.
            downloader: RPMDownloader instance.

        Returns:
            Metadata dictionary.
        """
        import socket

        host_summary = merger.get_host_summary()
        package_hosts = merger.get_package_to_hosts_map()

        # Count package types
        update_count = len([p for p in resolved if p.package_type == "update"])
        security_count = len([p for p in resolved if p.package_type == "security"])
        dependency_count = len([p for p in resolved if p.package_type == "dependency"])

        # Build package list with host mapping
        package_list = []
        for result in downloader.get_successful_downloads():
            pkg = result.package
            hosts_needing = package_hosts.get(pkg.name, [])

            package_list.append({
                "nevra": pkg.nevra,
                "type": pkg.package_type,
                "sha256": result.sha256,
                "size_bytes": result.local_path.stat().st_size if result.local_path else 0,
                "required_by": hosts_needing,
                "advisory_id": pkg.advisory_id,
            })

        # Build host package map
        host_package_map = {}
        for host_info in host_summary:
            host_id = host_info["host_id"]
            host_package_map[host_id] = [
                pkg["nevra"] for pkg in package_list
                if host_id in pkg.get("required_by", [])
            ]

        return {
            "schema_version": self.SCHEMA_VERSION,
            "bundle_id": self.bundle_id,
            "os_major": self.os_major,
            "created_at": timestamp.isoformat(),
            "builder_host": socket.gethostname(),
            "manifests_used": [
                {
                    "host_id": h["host_id"],
                    "manifest_hash": h["manifest_hash"],
                    "os_minor": h["os_minor"],
                }
                for h in host_summary
            ],
            "packages": {
                "total_count": len(package_list),
                "update_count": update_count,
                "security_count": security_count,
                "dependency_count": dependency_count,
                "size_bytes": downloader.get_total_size(),
            },
            "package_list": package_list,
            "host_package_map": host_package_map,
            "checksums": {
                "algorithm": "sha256",
                "bundle_hash": "",  # Will be updated after archive creation
            },
            "build_log": "build.log",
        }

    def _create_archive(self, source_dir: Path) -> Path:
        """Create compressed archive from source directory.

        Args:
            source_dir: Directory to archive.

        Returns:
            Path to created archive.
        """
        archive_name = f"{self.bundle_id}.tar.zst"
        archive_path = self.output_dir / archive_name

        # Try zstd compression first
        try:
            tar_path = self.output_dir / f"{self.bundle_id}.tar"

            # Create tar archive
            with tarfile.open(tar_path, "w") as tar:
                tar.add(source_dir, arcname=self.bundle_id)

            # Compress with zstd
            subprocess.run(
                ["zstd", "-19", "--rm", str(tar_path), "-o", str(archive_path)],
                check=True,
                capture_output=True,
            )

            return archive_path

        except (FileNotFoundError, subprocess.CalledProcessError):
            # Fall back to gzip
            archive_name = f"{self.bundle_id}.tar.gz"
            archive_path = self.output_dir / archive_name

            with tarfile.open(archive_path, "w:gz") as tar:
                tar.add(source_dir, arcname=self.bundle_id)

            return archive_path

    def _compute_file_hash(self, filepath: Path) -> str:
        """Compute SHA256 hash of a file.

        Args:
            filepath: Path to file.

        Returns:
            Hex-encoded SHA256 hash.
        """
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


def main():
    """CLI entry point for bundle building."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Build Policy B RPM bundle"
    )
    parser.add_argument(
        "--manifests",
        required=True,
        help="Directory containing host manifests",
    )
    parser.add_argument(
        "--os",
        required=True,
        choices=["rhel8", "rhel9"],
        help="Target OS version",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=".",
        help="Output directory for bundle",
    )
    parser.add_argument(
        "--work-dir",
        help="Working directory for intermediate files",
    )

    args = parser.parse_args()

    os_major = 8 if args.os == "rhel8" else 9

    builder = BundleBuilder(
        os_major=os_major,
        manifest_dir=args.manifests,
        output_dir=args.output,
        work_dir=args.work_dir,
    )

    try:
        bundle_path = builder.build()
        print(f"\nBundle created successfully: {bundle_path}")
    except Exception as e:
        print(f"\nBundle build failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
