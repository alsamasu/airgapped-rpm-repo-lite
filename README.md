# Airgapped RPM Repository - Lite Edition

A lightweight, manifest-driven RPM synchronization system using **Policy B: Installed-Package Closure**.

## Overview

This system replaces Foreman/Katello with a simple, targeted approach that:
- Downloads ONLY RPMs required to update currently installed packages
- Includes all dependencies needed for successful `dnf upgrade`
- Avoids mirroring full repositories
- Remains compatible with fully air-gapped environments

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL (Connected)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐                              ┌──────────────┐            │
│   │  ext-rhel8   │                              │  ext-rhel9   │            │
│   │  RHEL 8.10   │                              │  RHEL 9.6    │            │
│   │              │                              │              │            │
│   │ - Parse      │                              │ - Parse      │            │
│   │   manifests  │                              │   manifests  │            │
│   │ - Compute    │                              │ - Compute    │            │
│   │   updates    │                              │   updates    │            │
│   │ - Resolve    │                              │ - Resolve    │            │
│   │   deps       │                              │   deps       │            │
│   │ - Download   │                              │ - Download   │            │
│   │   RPMs       │                              │   RPMs       │            │
│   │ - Build      │                              │ - Build      │            │
│   │   bundle     │                              │   bundle     │            │
│   └──────┬───────┘                              └──────┬───────┘            │
│          │                                             │                    │
│          │  bundle-rhel8-<ts>.tar.zst                  │  bundle-rhel9-...  │
│          ▼                                             ▼                    │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │                    PHYSICAL MEDIA TRANSFER                       │       │
│   │              (USB drive, DVD, secure file transfer)              │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

                              ════════════════════
                                   AIR GAP
                              ════════════════════

┌─────────────────────────────────────────────────────────────────────────────┐
│                           INTERNAL (Air-gapped)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐                              ┌──────────────┐            │
│   │  int-rhel8   │                              │  int-rhel9   │            │
│   │              │                              │              │            │
│   │ - Verify     │                              │ - Verify     │            │
│   │   checksums  │                              │   checksums  │            │
│   │ - Extract    │                              │ - Extract    │            │
│   │   bundle     │                              │   bundle     │            │
│   │ - Publish    │                              │ - Publish    │            │
│   │   via HTTPS  │                              │   via HTTPS  │            │
│   │              │                              │              │            │
│   │ /repos/      │                              │ /repos/      │            │
│   │   rhel8/     │                              │   rhel9/     │            │
│   │     current  │                              │     current  │            │
│   └──────┬───────┘                              └──────┬───────┘            │
│          │                                             │                    │
│          │  HTTPS (TLS)                                │  HTTPS (TLS)       │
│          ▼                                             ▼                    │
│   ┌─────────────────────────────────────────────────────────────────┐       │
│   │                     INTERNAL RHEL HOSTS                          │       │
│   │                                                                  │       │
│   │   rhel8-host-01   rhel8-host-02   rhel9-host-01   rhel9-host-02 │       │
│   │                                                                  │       │
│   │   dnf upgrade -y  (uses internal repos, no internet required)    │       │
│   └─────────────────────────────────────────────────────────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Policy B: Installed-Package Closure

For each OS major version:

1. **Start** from the list of RPMs currently installed on target hosts
2. **Determine** available updates for those packages
3. **Download**:
   - Updated RPMs
   - All required dependencies for successful offline `dnf upgrade`
4. **Do NOT download**:
   - RPMs unrelated to installed packages
   - Entire repositories
   - Optional/debug/source packages

### Security Focus

- Prefer security updates when available
- Non-security updates allowed ONLY if required to satisfy dependency closure
- All included RPMs are logged and traceable

## Quick Start

### 1. Collect Manifests (from internal hosts)

```bash
cd ansible
ansible-playbook -i inventories/hosts.yml playbooks/collect_manifests.yml
```

### 2. Build Bundle (on external builders)

```bash
# On ext-rhel8
./scripts/external/build_bundle.sh --manifests /path/to/manifests --os rhel8

# On ext-rhel9
./scripts/external/build_bundle.sh --manifests /path/to/manifests --os rhel9
```

### 3. Transfer Bundle (across air gap)

Copy `bundle-rhel8-<timestamp>.tar.zst` to internal network via approved media.

### 4. Import and Publish (on internal servers)

```bash
# On int-rhel8
./scripts/internal/import_bundle.sh /path/to/bundle-rhel8-*.tar.zst

# On int-rhel9
./scripts/internal/import_bundle.sh /path/to/bundle-rhel9-*.tar.zst
```

### 5. Patch Hosts

```bash
cd ansible
ansible-playbook -i inventories/hosts.yml playbooks/patch_hosts.yml
```

## Directory Structure

```
airgapped-rpm-repo-lite/
├── ansible/                    # Ansible automation
│   ├── playbooks/              # Main playbooks
│   ├── roles/                  # Reusable roles
│   ├── inventories/            # Host inventories
│   └── artifacts/              # Collected manifests
├── scripts/                    # Shell scripts
│   ├── external/               # External builder scripts
│   ├── internal/               # Internal server scripts
│   └── common/                 # Shared utilities
├── src/                        # Python modules
│   ├── bundle_builder/         # Bundle build logic
│   └── manifest_tools/         # Manifest processing
├── schemas/                    # JSON schemas
├── docs/                       # Documentation
├── automation/                 # E2E testing
│   ├── artifacts/              # Test evidence
│   └── powercli/               # vSphere automation
└── tests/                      # Unit tests
```

## Documentation

- [Deployment Guide](docs/deployment.md) - Architecture, server roles, prerequisites
- [Operations Guide](docs/operations.md) - Monthly workflow
- [Caveats](docs/caveats.md) - Tradeoffs vs Foreman/Katello

## Non-Goals (Explicit)

This system intentionally does NOT provide:
- Content Views
- Lifecycle environments
- Errata promotion workflows
- Full repository mirroring
- Foreman/Katello components

These tradeoffs enable:
- Smaller bundles (GBs instead of TBs)
- Faster monthly cycles
- Simpler infrastructure
- Lower operational overhead

## License

MIT License - See [LICENSE](LICENSE) for details.
