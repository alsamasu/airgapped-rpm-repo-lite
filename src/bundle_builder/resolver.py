#!/usr/bin/env python3
"""
Dependency resolver for Policy B installed-package closure.

Uses DNF APIs to compute the full update set with dependency closure.
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ResolvedPackage:
    """A resolved package for download."""
    name: str
    epoch: str
    version: str
    release: str
    arch: str
    nevra: str
    repo_id: str
    package_type: str  # 'update', 'dependency', or 'security'
    size_bytes: int = 0
    advisory_id: str | None = None
    required_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "epoch": self.epoch,
            "version": self.version,
            "release": self.release,
            "arch": self.arch,
            "nevra": self.nevra,
            "repo_id": self.repo_id,
            "type": self.package_type,
            "size_bytes": self.size_bytes,
            "advisory_id": self.advisory_id,
            "required_by": self.required_by,
        }


class DependencyResolver:
    """Resolve package updates and dependencies using DNF."""

    def __init__(self, installed_packages: list[str], prefer_security: bool = True):
        """Initialize the resolver.

        Args:
            installed_packages: List of installed package names.
            prefer_security: Prefer security updates when available.
        """
        self.installed_packages = set(installed_packages)
        self.prefer_security = prefer_security
        self.resolved: list[ResolvedPackage] = []
        self.errors: list[str] = []

    def resolve(self) -> list[ResolvedPackage]:
        """Resolve all updates and dependencies.

        Returns:
            List of resolved packages to download.
        """
        self.resolved = []
        self.errors = []

        # Step 1: Get available updates for installed packages
        updates = self._get_available_updates()
        if not updates:
            print("No updates available for installed packages.")
            return []

        print(f"Found {len(updates)} packages with available updates.")

        # Step 2: Get security updates specifically
        security_updates = set()
        if self.prefer_security:
            security_updates = self._get_security_updates()
            print(f"Found {len(security_updates)} security updates.")

        # Step 3: Resolve full dependency closure
        all_packages = self._resolve_dependencies(updates)

        # Step 4: Classify packages
        for pkg in all_packages:
            if pkg.name in security_updates:
                pkg.package_type = "security"
            elif pkg.name in updates:
                pkg.package_type = "update"
            else:
                pkg.package_type = "dependency"

            self.resolved.append(pkg)

        return self.resolved

    def _get_available_updates(self) -> set[str]:
        """Get list of packages that have available updates.

        Returns:
            Set of package names with updates.
        """
        updates = set()

        try:
            # Use dnf check-update to find available updates
            result = subprocess.run(
                ["dnf", "check-update", "--quiet"],
                capture_output=True,
                text=True,
            )

            # Exit code 100 means updates are available
            if result.returncode not in (0, 100):
                self.errors.append(f"dnf check-update failed: {result.stderr}")
                return updates

            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("Obsoleting"):
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    # Package name is first field (may include arch)
                    pkg_with_arch = parts[0]
                    pkg_name = pkg_with_arch.rsplit(".", 1)[0]

                    # Only include if it's in our installed set
                    if pkg_name in self.installed_packages:
                        updates.add(pkg_name)

        except subprocess.CalledProcessError as e:
            self.errors.append(f"Failed to check updates: {e}")

        return updates

    def _get_security_updates(self) -> set[str]:
        """Get list of packages with security updates.

        Returns:
            Set of package names with security updates.
        """
        security_pkgs = set()

        try:
            result = subprocess.run(
                ["dnf", "updateinfo", "list", "--security", "--available"],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                return security_pkgs

            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    # Package name is typically the third field
                    pkg_with_arch = parts[2]
                    pkg_name = pkg_with_arch.rsplit(".", 1)[0]
                    # Strip version info if present
                    pkg_name = pkg_name.split("-")[0] if "-" in pkg_name else pkg_name
                    security_pkgs.add(pkg_name)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.errors.append(f"Failed to get security updates: {e}")

        return security_pkgs

    def _resolve_dependencies(self, update_packages: set[str]) -> list[ResolvedPackage]:
        """Resolve full dependency closure for updates.

        Args:
            update_packages: Set of package names to update.

        Returns:
            List of all packages needed (updates + dependencies).
        """
        resolved = []

        if not update_packages:
            return resolved

        try:
            # Use dnf download --resolve to compute dependencies
            # First, do a dry-run to see what would be downloaded
            pkg_list = list(update_packages)

            result = subprocess.run(
                [
                    "dnf", "download",
                    "--resolve",
                    "--downloadonly",
                    "--destdir=/tmp/dnf-resolve-test",
                    "--assumeno",
                    "-v",
                ] + pkg_list,
                capture_output=True,
                text=True,
            )

            # Parse the output to find all packages that would be downloaded
            in_package_list = False
            for line in result.stdout.splitlines() + result.stderr.splitlines():
                line = line.strip()

                if "Installing:" in line or "Upgrading:" in line:
                    in_package_list = True
                    continue

                if in_package_list and line.startswith("Installing dependencies:"):
                    continue

                # Parse package lines
                if in_package_list and line:
                    pkg = self._parse_package_line(line)
                    if pkg:
                        resolved.append(pkg)

        except subprocess.CalledProcessError as e:
            self.errors.append(f"Failed to resolve dependencies: {e}")

        # If parsing failed, try alternative method using repoquery
        if not resolved:
            resolved = self._resolve_via_repoquery(update_packages)

        return resolved

    def _resolve_via_repoquery(self, packages: set[str]) -> list[ResolvedPackage]:
        """Alternative resolution using dnf repoquery.

        Args:
            packages: Set of package names.

        Returns:
            List of resolved packages.
        """
        resolved = []
        processed = set()
        to_process = list(packages)

        while to_process:
            pkg_name = to_process.pop(0)
            if pkg_name in processed:
                continue
            processed.add(pkg_name)

            try:
                # Get latest version available
                result = subprocess.run(
                    [
                        "dnf", "repoquery",
                        "--latest-limit=1",
                        "--queryformat",
                        "%{name}|%{epoch}|%{version}|%{release}|%{arch}|%{reponame}|%{size}",
                        pkg_name,
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )

                for line in result.stdout.splitlines():
                    if not line.strip():
                        continue

                    parts = line.split("|")
                    if len(parts) < 7:
                        continue

                    name, epoch, version, release, arch, repo, size = parts[:7]

                    # Skip if already resolved
                    nevra = f"{name}-{epoch}:{version}-{release}.{arch}"
                    if any(p.nevra == nevra for p in resolved):
                        continue

                    pkg = ResolvedPackage(
                        name=name,
                        epoch=epoch if epoch != "(none)" else "0",
                        version=version,
                        release=release,
                        arch=arch,
                        nevra=nevra,
                        repo_id=repo,
                        package_type="update" if name in packages else "dependency",
                        size_bytes=int(size) if size.isdigit() else 0,
                    )
                    resolved.append(pkg)

                # Get dependencies
                dep_result = subprocess.run(
                    [
                        "dnf", "repoquery",
                        "--requires",
                        "--resolve",
                        "--latest-limit=1",
                        "--queryformat=%{name}",
                        pkg_name,
                    ],
                    capture_output=True,
                    text=True,
                )

                for dep_line in dep_result.stdout.splitlines():
                    dep_name = dep_line.strip()
                    if dep_name and dep_name not in processed:
                        to_process.append(dep_name)

            except subprocess.CalledProcessError:
                continue

        return resolved

    def _parse_package_line(self, line: str) -> ResolvedPackage | None:
        """Parse a package line from dnf output.

        Args:
            line: Line from dnf output.

        Returns:
            ResolvedPackage or None if parsing failed.
        """
        # Try to parse lines like: "package-name-1.0-1.el9.x86_64   repo_id   123 k"
        parts = line.split()
        if len(parts) < 2:
            return None

        nevra = parts[0]
        repo_id = parts[1] if len(parts) > 1 else "unknown"

        # Parse NEVRA
        try:
            # Split arch
            if "." in nevra:
                base, arch = nevra.rsplit(".", 1)
            else:
                return None

            # Split release
            if "-" in base:
                base2, release = base.rsplit("-", 1)
            else:
                return None

            # Split version (may include epoch)
            if "-" in base2:
                name, version = base2.rsplit("-", 1)
            else:
                return None

            # Handle epoch
            epoch = "0"
            if ":" in version:
                epoch, version = version.split(":", 1)

            return ResolvedPackage(
                name=name,
                epoch=epoch,
                version=version,
                release=release,
                arch=arch,
                nevra=nevra,
                repo_id=repo_id,
                package_type="update",
            )

        except Exception:
            return None

    def export_resolution(self, output_path: str | Path) -> Path:
        """Export resolution results to JSON.

        Args:
            output_path: Output file path.

        Returns:
            Path to output file.
        """
        path = Path(output_path)

        data = {
            "installed_count": len(self.installed_packages),
            "resolved_count": len(self.resolved),
            "update_count": len([p for p in self.resolved if p.package_type == "update"]),
            "security_count": len([p for p in self.resolved if p.package_type == "security"]),
            "dependency_count": len([p for p in self.resolved if p.package_type == "dependency"]),
            "total_size_bytes": sum(p.size_bytes for p in self.resolved),
            "packages": [p.to_dict() for p in self.resolved],
            "errors": self.errors,
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        return path


def main():
    """CLI entry point for dependency resolution."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Resolve package updates and dependencies"
    )
    parser.add_argument(
        "--packages",
        nargs="+",
        help="Package names to resolve",
    )
    parser.add_argument(
        "--package-file",
        help="File containing package names (one per line)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file for resolution results",
    )
    parser.add_argument(
        "--no-security-preference",
        action="store_true",
        help="Don't prefer security updates",
    )

    args = parser.parse_args()

    packages = set()
    if args.packages:
        packages.update(args.packages)
    if args.package_file:
        with open(args.package_file) as f:
            for line in f:
                pkg = line.strip()
                if pkg and not pkg.startswith("#"):
                    packages.add(pkg)

    if not packages:
        print("No packages specified.", file=sys.stderr)
        sys.exit(1)

    resolver = DependencyResolver(
        list(packages),
        prefer_security=not args.no_security_preference,
    )

    resolved = resolver.resolve()
    print(f"Resolved {len(resolved)} packages.")

    if args.output:
        resolver.export_resolution(args.output)
        print(f"Results written to: {args.output}")
    else:
        for pkg in resolved:
            print(f"  [{pkg.package_type}] {pkg.nevra}")


if __name__ == "__main__":
    main()
