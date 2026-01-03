#!/usr/bin/env python3
"""
RPM downloader for Policy B installed-package closure.

Downloads resolved RPMs from Red Hat CDN.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .resolver import ResolvedPackage


@dataclass
class DownloadResult:
    """Result of a package download."""
    package: ResolvedPackage
    success: bool
    local_path: Path | None
    sha256: str | None
    error: str | None


class RPMDownloader:
    """Download RPMs using DNF."""

    def __init__(self, download_dir: str | Path):
        """Initialize the downloader.

        Args:
            download_dir: Directory to store downloaded RPMs.
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[DownloadResult] = []

    def download_packages(
        self,
        packages: list[ResolvedPackage],
        skip_existing: bool = True,
    ) -> list[DownloadResult]:
        """Download all packages.

        Args:
            packages: List of packages to download.
            skip_existing: Skip packages that already exist locally.

        Returns:
            List of download results.
        """
        self.results = []

        # Group packages by name for bulk download
        package_names = [pkg.name for pkg in packages]

        if not package_names:
            print("No packages to download.")
            return []

        print(f"Downloading {len(package_names)} packages to {self.download_dir}")

        try:
            # Use dnf download with resolve to get packages + deps
            result = subprocess.run(
                [
                    "dnf", "download",
                    "--resolve",
                    "--alldeps",
                    f"--destdir={self.download_dir}",
                    "-y",
                ] + package_names,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print(f"Warning: dnf download returned {result.returncode}")
                print(result.stderr)

        except subprocess.CalledProcessError as e:
            print(f"Error during download: {e}", file=sys.stderr)

        # Verify what was downloaded
        self._verify_downloads(packages)

        return self.results

    def _verify_downloads(self, packages: list[ResolvedPackage]) -> None:
        """Verify downloaded packages and compute checksums.

        Args:
            packages: List of expected packages.
        """
        # Get list of downloaded RPMs
        downloaded_rpms = list(self.download_dir.glob("*.rpm"))
        rpm_by_name: dict[str, Path] = {}

        for rpm_path in downloaded_rpms:
            # Extract package name from filename
            basename = rpm_path.stem
            # Parse name from NEVRA pattern
            parts = basename.rsplit("-", 2)
            if len(parts) >= 3:
                pkg_name = parts[0]
                rpm_by_name[pkg_name] = rpm_path

        for pkg in packages:
            rpm_path = rpm_by_name.get(pkg.name)

            if rpm_path and rpm_path.exists():
                sha256 = self._compute_sha256(rpm_path)
                self.results.append(DownloadResult(
                    package=pkg,
                    success=True,
                    local_path=rpm_path,
                    sha256=sha256,
                    error=None,
                ))
            else:
                # Try to find by partial match
                found = False
                for rpm_file in downloaded_rpms:
                    if rpm_file.name.startswith(f"{pkg.name}-"):
                        sha256 = self._compute_sha256(rpm_file)
                        self.results.append(DownloadResult(
                            package=pkg,
                            success=True,
                            local_path=rpm_file,
                            sha256=sha256,
                            error=None,
                        ))
                        found = True
                        break

                if not found:
                    self.results.append(DownloadResult(
                        package=pkg,
                        success=False,
                        local_path=None,
                        sha256=None,
                        error="Package not found in downloads",
                    ))

    def _compute_sha256(self, filepath: Path) -> str:
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

    def get_successful_downloads(self) -> list[DownloadResult]:
        """Get list of successful downloads.

        Returns:
            List of successful download results.
        """
        return [r for r in self.results if r.success]

    def get_failed_downloads(self) -> list[DownloadResult]:
        """Get list of failed downloads.

        Returns:
            List of failed download results.
        """
        return [r for r in self.results if not r.success]

    def get_total_size(self) -> int:
        """Get total size of downloaded RPMs in bytes.

        Returns:
            Total size in bytes.
        """
        total = 0
        for result in self.results:
            if result.success and result.local_path:
                total += result.local_path.stat().st_size
        return total

    def generate_checksums_file(self, output_path: str | Path | None = None) -> Path:
        """Generate SHA256SUMS file for downloads.

        Args:
            output_path: Output path. Defaults to SHA256SUMS in download_dir.

        Returns:
            Path to checksums file.
        """
        if output_path is None:
            output_path = self.download_dir / "SHA256SUMS"
        else:
            output_path = Path(output_path)

        lines = []
        for result in sorted(self.results, key=lambda r: r.package.name):
            if result.success and result.sha256 and result.local_path:
                lines.append(f"{result.sha256}  {result.local_path.name}")

        with open(output_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        return output_path


def download_all_updates(
    package_list: list[str],
    output_dir: str | Path,
) -> tuple[list[DownloadResult], list[str]]:
    """Convenience function to download all updates for packages.

    Args:
        package_list: List of installed package names.
        output_dir: Directory for downloads.

    Returns:
        Tuple of (download results, error messages).
    """
    from .resolver import DependencyResolver

    # Resolve dependencies
    resolver = DependencyResolver(package_list)
    resolved = resolver.resolve()

    if not resolved:
        return [], ["No packages to download"]

    # Download packages
    downloader = RPMDownloader(output_dir)
    results = downloader.download_packages(resolved)

    return results, resolver.errors


def main():
    """CLI entry point for RPM download."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Download RPMs for Policy B bundle"
    )
    parser.add_argument(
        "--packages",
        nargs="+",
        help="Package names to download",
    )
    parser.add_argument(
        "--package-file",
        help="File containing package names",
    )
    parser.add_argument(
        "-d",
        "--dest",
        required=True,
        help="Download destination directory",
    )
    parser.add_argument(
        "--checksums",
        action="store_true",
        help="Generate SHA256SUMS file",
    )

    args = parser.parse_args()

    packages = []
    if args.packages:
        packages.extend(args.packages)
    if args.package_file:
        with open(args.package_file) as f:
            for line in f:
                pkg = line.strip()
                if pkg and not pkg.startswith("#"):
                    packages.append(pkg)

    if not packages:
        print("No packages specified.", file=sys.stderr)
        sys.exit(1)

    results, errors = download_all_updates(packages, args.dest)

    success_count = len([r for r in results if r.success])
    fail_count = len([r for r in results if not r.success])

    print(f"Downloaded: {success_count}, Failed: {fail_count}")

    if errors:
        print("Errors:")
        for error in errors:
            print(f"  - {error}")

    if args.checksums and results:
        downloader = RPMDownloader(args.dest)
        downloader.results = results
        checksums_path = downloader.generate_checksums_file()
        print(f"Checksums written to: {checksums_path}")


if __name__ == "__main__":
    main()
