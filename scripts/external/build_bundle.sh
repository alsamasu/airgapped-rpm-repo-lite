#!/bin/bash
# Build Policy B RPM bundle on external builder
#
# This script:
# 1. Parses manifests for the target OS version
# 2. Computes update set with dependency closure
# 3. Downloads required RPMs from Red Hat CDN
# 4. Creates self-contained repository bundle
#
# Usage:
#   ./build_bundle.sh --manifests /path/to/manifests --os rhel8
#   ./build_bundle.sh --manifests /path/to/manifests --os rhel9 --output /path/to/output

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source common functions
source "${SCRIPT_DIR}/../common/logging.sh"
source "${SCRIPT_DIR}/../common/validation.sh"

# Default values
MANIFEST_DIR=""
OS_VERSION=""
OUTPUT_DIR="${PWD}"
WORK_DIR="/tmp/bundle-build-$$"
KEEP_WORK_DIR=false

# Parse arguments
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Build Policy B RPM bundle from host manifests.

Options:
    -m, --manifests DIR    Directory containing host manifests (required)
    -o, --os VERSION       Target OS version: rhel8 or rhel9 (required)
    -d, --output DIR       Output directory for bundle (default: current directory)
    -w, --work-dir DIR     Working directory (default: /tmp/bundle-build-PID)
    -k, --keep-work        Keep working directory after build
    -h, --help             Show this help message

Examples:
    $(basename "$0") --manifests ./manifests --os rhel8
    $(basename "$0") -m ./manifests -o rhel9 -d /var/bundles
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--manifests)
            MANIFEST_DIR="$2"
            shift 2
            ;;
        -o|--os)
            OS_VERSION="$2"
            shift 2
            ;;
        -d|--output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -w|--work-dir)
            WORK_DIR="$2"
            shift 2
            ;;
        -k|--keep-work)
            KEEP_WORK_DIR=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

# Validate required arguments
[[ -z "$MANIFEST_DIR" ]] && die "Manifest directory is required. Use --manifests"
[[ -z "$OS_VERSION" ]] && die "OS version is required. Use --os rhel8 or --os rhel9"
[[ "$OS_VERSION" =~ ^rhel[89]$ ]] || die "Invalid OS version: $OS_VERSION (expected rhel8 or rhel9)"

OS_MAJOR="${OS_VERSION#rhel}"

log_script_start

# Validate environment
log_info "Validating environment..."
require_command dnf
require_command createrepo_c || require_command createrepo
require_command python3
require_command tar

# Validate OS version matches builder
validate_os_version "$OS_MAJOR"

# Validate subscription
validate_subscription || log_warn "Proceeding without subscription validation"

# Validate manifest directory
validate_directory "$MANIFEST_DIR" false || die "Manifest directory not accessible"

# Count manifests
MANIFEST_COUNT=$(find "$MANIFEST_DIR" -name "*.json" -type f | wc -l)
[[ "$MANIFEST_COUNT" -eq 0 ]] && die "No manifest files found in $MANIFEST_DIR"
log_info "Found $MANIFEST_COUNT manifest files"

# Create output and work directories
validate_directory "$OUTPUT_DIR" true
validate_directory "$WORK_DIR" true

# Check disk space (require at least 50GB)
require_disk_space "$WORK_DIR" 50

# Cleanup handler
cleanup() {
    if [[ "$KEEP_WORK_DIR" != "true" && -d "$WORK_DIR" ]]; then
        log_info "Cleaning up work directory..."
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT

# Generate timestamp for bundle ID
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
BUNDLE_ID="bundle-${OS_VERSION}-${TIMESTAMP}"
BUNDLE_WORK="${WORK_DIR}/${BUNDLE_ID}"
RPMS_DIR="${BUNDLE_WORK}/rpms"
MANIFESTS_COPY="${BUNDLE_WORK}/manifests"

mkdir -p "$RPMS_DIR" "$MANIFESTS_COPY"

log_info "Bundle ID: $BUNDLE_ID"
log_info "Working directory: $BUNDLE_WORK"

# Step 1: Copy and validate manifests
log_info "Step 1: Processing manifests..."

VALID_MANIFESTS=0
for manifest in "$MANIFEST_DIR"/*.json; do
    [[ -f "$manifest" ]] || continue
    
    # Check OS version in manifest
    manifest_os=$(python3 -c "import json; print(json.load(open('$manifest')).get('os', {}).get('major', 0))" 2>/dev/null || echo "0")
    
    if [[ "$manifest_os" == "$OS_MAJOR" ]]; then
        if validate_manifest "$manifest"; then
            cp "$manifest" "$MANIFESTS_COPY/"
            ((VALID_MANIFESTS++))
        fi
    fi
done

[[ "$VALID_MANIFESTS" -eq 0 ]] && die "No valid RHEL $OS_MAJOR manifests found"
log_info "Validated $VALID_MANIFESTS manifests for RHEL $OS_MAJOR"

# Step 2: Merge manifests and extract package list
log_info "Step 2: Merging manifests..."

PACKAGE_LIST="${BUNDLE_WORK}/installed-packages.txt"
MERGE_REPORT="${BUNDLE_WORK}/merge-report.json"

python3 -c "
import json
import sys
from pathlib import Path

manifest_dir = Path('$MANIFESTS_COPY')
packages = set()
manifests_used = []

for manifest_file in manifest_dir.glob('*.json'):
    with open(manifest_file) as f:
        manifest = json.load(f)
    
    host_id = manifest.get('host_id', manifest_file.stem)
    manifests_used.append({
        'host_id': host_id,
        'os_minor': manifest.get('os', {}).get('minor', 0)
    })
    
    for rpm in manifest.get('installed_rpms', []):
        packages.add(rpm.get('name', ''))

# Write package list
with open('$PACKAGE_LIST', 'w') as f:
    for pkg in sorted(packages):
        if pkg:
            f.write(pkg + '\n')

# Write merge report
report = {
    'manifests_count': len(manifests_used),
    'unique_packages': len(packages),
    'manifests': manifests_used
}
with open('$MERGE_REPORT', 'w') as f:
    json.dump(report, f, indent=2)

print(f'Merged {len(manifests_used)} manifests, {len(packages)} unique packages')
"

PACKAGE_COUNT=$(wc -l < "$PACKAGE_LIST")
log_info "Found $PACKAGE_COUNT unique installed packages"

# Step 3: Check for updates
log_info "Step 3: Checking for available updates..."

UPDATE_LIST="${BUNDLE_WORK}/available-updates.txt"
dnf check-update --quiet 2>/dev/null | grep -v "^$" | grep -v "Obsoleting" | awk '{print $1}' | cut -d'.' -f1 | sort -u > "$UPDATE_LIST" || true

UPDATE_COUNT=$(wc -l < "$UPDATE_LIST")
log_info "Found $UPDATE_COUNT packages with available updates"

if [[ "$UPDATE_COUNT" -eq 0 ]]; then
    log_warn "No updates available. Creating empty bundle."
fi

# Step 4: Download updates with dependencies
log_info "Step 4: Downloading RPMs with dependencies..."

# Filter updates to only packages we have installed
DOWNLOAD_LIST="${BUNDLE_WORK}/download-list.txt"
comm -12 <(sort "$PACKAGE_LIST") <(sort "$UPDATE_LIST") > "$DOWNLOAD_LIST"

DOWNLOAD_COUNT=$(wc -l < "$DOWNLOAD_LIST")
log_info "Will download updates for $DOWNLOAD_COUNT installed packages"

if [[ "$DOWNLOAD_COUNT" -gt 0 ]]; then
    log_info "Downloading packages (this may take a while)..."
    
    # Download with dependency resolution
    if ! dnf download \
        --resolve \
        --alldeps \
        --destdir="$RPMS_DIR" \
        $(cat "$DOWNLOAD_LIST") \
        2>&1 | tee "${BUNDLE_WORK}/download.log"; then
        log_warn "Some packages may have failed to download"
    fi
fi

RPM_COUNT=$(find "$RPMS_DIR" -name "*.rpm" | wc -l)
log_info "Downloaded $RPM_COUNT RPM files"

# Step 5: Generate repository metadata
log_info "Step 5: Generating repository metadata..."

if command -v createrepo_c &>/dev/null; then
    createrepo_c --update "$RPMS_DIR" 2>&1 | tee -a "${BUNDLE_WORK}/createrepo.log"
else
    createrepo --update "$RPMS_DIR" 2>&1 | tee -a "${BUNDLE_WORK}/createrepo.log"
fi

log_success "Repository metadata generated"

# Step 6: Generate checksums
log_info "Step 6: Generating checksums..."

CHECKSUM_FILE="${BUNDLE_WORK}/SHA256SUMS"
(cd "$RPMS_DIR" && find . -name "*.rpm" -exec sha256sum {} \; | sort) > "$CHECKSUM_FILE"
log_info "Generated checksums for $RPM_COUNT RPMs"

# Step 7: Generate bundle metadata
log_info "Step 7: Generating bundle metadata..."

TOTAL_SIZE=$(du -sb "$RPMS_DIR" | awk '{print $1}')

python3 -c "
import json
import socket
from datetime import datetime, timezone
from pathlib import Path

# Load merge report
with open('$MERGE_REPORT') as f:
    merge_data = json.load(f)

# Count RPMs by type (simplified - all as updates for now)
rpm_count = len(list(Path('$RPMS_DIR').glob('*.rpm')))

metadata = {
    'schema_version': '1.0',
    'bundle_id': '$BUNDLE_ID',
    'os_major': $OS_MAJOR,
    'created_at': datetime.now(timezone.utc).isoformat(),
    'builder_host': socket.gethostname(),
    'manifests_used': merge_data.get('manifests', []),
    'packages': {
        'total_count': rpm_count,
        'update_count': rpm_count,
        'dependency_count': 0,
        'size_bytes': $TOTAL_SIZE
    },
    'checksums': {
        'algorithm': 'sha256',
        'bundle_hash': ''  # Will be updated after archive creation
    },
    'build_log': 'build.log'
}

with open('${BUNDLE_WORK}/metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

print('Metadata generated')
"

# Step 8: Create build log
log_info "Step 8: Creating build log..."

BUILD_LOG="${BUNDLE_WORK}/build.log"
cat > "$BUILD_LOG" <<EOF
Bundle Build Log
================
Bundle ID: $BUNDLE_ID
Builder: $(hostname)
Timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
OS Version: RHEL $OS_MAJOR

Manifests Processed: $VALID_MANIFESTS
Unique Packages: $PACKAGE_COUNT
Updates Available: $UPDATE_COUNT
Packages Downloaded: $DOWNLOAD_COUNT
RPMs in Bundle: $RPM_COUNT
Total Size: $(numfmt --to=iec $TOTAL_SIZE)

Build completed successfully.
EOF

# Step 9: Create archive
log_info "Step 9: Creating bundle archive..."

ARCHIVE_NAME="${BUNDLE_ID}.tar.zst"
ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"

# Try zstd first, fall back to gzip
if command -v zstd &>/dev/null; then
    tar -C "$WORK_DIR" -cf - "$BUNDLE_ID" | zstd -19 -T0 -o "$ARCHIVE_PATH"
else
    log_warn "zstd not found, using gzip compression"
    ARCHIVE_NAME="${BUNDLE_ID}.tar.gz"
    ARCHIVE_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"
    tar -C "$WORK_DIR" -czf "$ARCHIVE_PATH" "$BUNDLE_ID"
fi

# Compute final hash
BUNDLE_HASH=$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')

# Update metadata with final hash
python3 -c "
import json
with open('${BUNDLE_WORK}/metadata.json', 'r+') as f:
    metadata = json.load(f)
    metadata['checksums']['bundle_hash'] = '$BUNDLE_HASH'
    f.seek(0)
    json.dump(metadata, f, indent=2)
    f.truncate()
"

# Create checksum file for bundle
echo "$BUNDLE_HASH  $ARCHIVE_NAME" > "${OUTPUT_DIR}/${BUNDLE_ID}.sha256"

# Display summary
log_info ""
log_success "=========================================="
log_success "Bundle Build Complete"
log_success "=========================================="
log_info "Bundle:    ${ARCHIVE_PATH}"
log_info "Size:      $(ls -lh "$ARCHIVE_PATH" | awk '{print $5}')"
log_info "SHA256:    ${BUNDLE_HASH}"
log_info "Checksum:  ${OUTPUT_DIR}/${BUNDLE_ID}.sha256"
log_info ""
log_info "Contents:"
log_info "  - RPMs:      $RPM_COUNT packages"
log_info "  - Manifests: $VALID_MANIFESTS hosts"
log_info "  - Metadata:  metadata.json"
log_info "  - Checksums: SHA256SUMS"
log_success "=========================================="

log_script_end 0
