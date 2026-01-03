#!/bin/bash
# Import and publish RPM bundle on internal server
#
# This script:
# 1. Verifies bundle integrity (checksums)
# 2. Extracts bundle to versioned path
# 3. Updates repodata if needed
# 4. Updates 'current' symlink
# 5. Verifies HTTPS accessibility
#
# Usage:
#   ./import_bundle.sh /path/to/bundle-rhel8-*.tar.zst
#   ./import_bundle.sh /path/to/bundle-rhel9-*.tar.gz --checksum /path/to/checksum.sha256

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Source common functions
source "${SCRIPT_DIR}/../common/logging.sh"
source "${SCRIPT_DIR}/../common/validation.sh"

# Default values
BUNDLE_FILE=""
CHECKSUM_FILE=""
REPO_BASE="/var/www/html/repos"
BACKUP_OLD=true
VERIFY_HTTPS=true

# Parse arguments
usage() {
    cat <<EOF
Usage: $(basename "$0") BUNDLE_FILE [OPTIONS]

Import and publish Policy B RPM bundle.

Arguments:
    BUNDLE_FILE            Path to bundle archive (.tar.zst or .tar.gz)

Options:
    -c, --checksum FILE    Checksum file for verification
    -r, --repo-base DIR    Repository base directory (default: /var/www/html/repos)
    --no-backup            Don't backup previous bundle
    --no-verify-https      Skip HTTPS verification
    -h, --help             Show this help message

Examples:
    $(basename "$0") /media/usb/bundle-rhel8-20240115T120000Z.tar.zst
    $(basename "$0") bundle-rhel9-*.tar.zst --checksum bundle.sha256
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--checksum)
            CHECKSUM_FILE="$2"
            shift 2
            ;;
        -r|--repo-base)
            REPO_BASE="$2"
            shift 2
            ;;
        --no-backup)
            BACKUP_OLD=false
            shift
            ;;
        --no-verify-https)
            VERIFY_HTTPS=false
            shift
            ;;
        -h|--help)
            usage
            ;;
        -*)
            die "Unknown option: $1"
            ;;
        *)
            if [[ -z "$BUNDLE_FILE" ]]; then
                BUNDLE_FILE="$1"
            else
                die "Unexpected argument: $1"
            fi
            shift
            ;;
    esac
done

# Validate bundle file
[[ -z "$BUNDLE_FILE" ]] && die "Bundle file is required"
[[ -f "$BUNDLE_FILE" ]] || die "Bundle file not found: $BUNDLE_FILE"

log_script_start

# Extract bundle ID and OS from filename
BUNDLE_NAME=$(basename "$BUNDLE_FILE")
if [[ "$BUNDLE_NAME" =~ ^bundle-(rhel[89])-([0-9]{8}T[0-9]{6}Z)\.(tar\.(zst|gz))$ ]]; then
    OS_VERSION="${BASH_REMATCH[1]}"
    BUNDLE_TIMESTAMP="${BASH_REMATCH[2]}"
    BUNDLE_ID="bundle-${OS_VERSION}-${BUNDLE_TIMESTAMP}"
else
    die "Invalid bundle filename format: $BUNDLE_NAME"
fi

OS_MAJOR="${OS_VERSION#rhel}"
REPO_PATH="${REPO_BASE}/${OS_VERSION}"

log_info "Bundle ID: $BUNDLE_ID"
log_info "OS Version: RHEL $OS_MAJOR"
log_info "Repository path: $REPO_PATH"

# Validate environment
log_info "Validating environment..."
require_root
require_command tar

# Validate OS version matches server
validate_os_version "$OS_MAJOR"

# Ensure repo base directory exists
validate_directory "$REPO_BASE" true

# Step 1: Verify bundle integrity
log_info "Step 1: Verifying bundle integrity..."

# If checksum file not provided, look for it next to bundle
if [[ -z "$CHECKSUM_FILE" ]]; then
    CHECKSUM_FILE="${BUNDLE_FILE%.tar.*}.sha256"
fi

if [[ -f "$CHECKSUM_FILE" ]]; then
    log_info "Using checksum file: $CHECKSUM_FILE"
    
    EXPECTED_HASH=$(cat "$CHECKSUM_FILE" | awk '{print $1}')
    log_info "Expected SHA256: $EXPECTED_HASH"
    
    log_info "Computing bundle checksum (this may take a moment)..."
    ACTUAL_HASH=$(sha256sum "$BUNDLE_FILE" | awk '{print $1}')
    log_info "Actual SHA256:   $ACTUAL_HASH"
    
    if [[ "$EXPECTED_HASH" != "$ACTUAL_HASH" ]]; then
        die "CHECKSUM MISMATCH! Bundle may be corrupted or tampered with."
    fi
    log_success "Checksum verified successfully"
else
    log_warn "No checksum file found - skipping integrity verification"
    log_warn "This is not recommended for production use!"
fi

# Verify archive integrity
log_info "Verifying archive integrity..."
validate_bundle "$BUNDLE_FILE" "" || die "Bundle archive verification failed"

# Step 2: Create versioned directory
log_info "Step 2: Preparing extraction directory..."

EXTRACT_PATH="${REPO_PATH}/${BUNDLE_ID}"

if [[ -d "$EXTRACT_PATH" ]]; then
    log_warn "Bundle already exists: $EXTRACT_PATH"
    log_warn "Removing existing bundle..."
    rm -rf "$EXTRACT_PATH"
fi

mkdir -p "$EXTRACT_PATH"

# Step 3: Extract bundle
log_info "Step 3: Extracting bundle..."

BUNDLE_EXT="${BUNDLE_NAME##*.}"
case "$BUNDLE_EXT" in
    zst)
        require_command zstd
        zstd -d "$BUNDLE_FILE" -c | tar -xf - -C "$REPO_PATH"
        ;;
    gz)
        tar -xzf "$BUNDLE_FILE" -C "$REPO_PATH"
        ;;
    *)
        die "Unsupported archive format: $BUNDLE_EXT"
        ;;
esac

# Verify extraction
if [[ ! -d "${EXTRACT_PATH}/rpms" ]]; then
    die "Extraction failed: rpms directory not found"
fi

log_success "Bundle extracted to: $EXTRACT_PATH"

# Step 4: Verify repodata
log_info "Step 4: Verifying repository metadata..."

REPODATA_PATH="${EXTRACT_PATH}/rpms/repodata"

if [[ -d "$REPODATA_PATH" ]]; then
    log_info "Repodata found: $REPODATA_PATH"
else
    log_warn "Repodata not found, regenerating..."
    
    if command -v createrepo_c &>/dev/null; then
        createrepo_c "${EXTRACT_PATH}/rpms"
    else
        createrepo "${EXTRACT_PATH}/rpms"
    fi
fi

# Verify repomd.xml exists
if [[ ! -f "${REPODATA_PATH}/repomd.xml" ]]; then
    die "Repository metadata is invalid: repomd.xml not found"
fi

log_success "Repository metadata verified"

# Step 5: Backup old current link
log_info "Step 5: Updating repository symlinks..."

CURRENT_LINK="${REPO_PATH}/current"
PREVIOUS_LINK="${REPO_PATH}/previous"

if [[ -L "$CURRENT_LINK" ]]; then
    OLD_TARGET=$(readlink -f "$CURRENT_LINK")
    OLD_BUNDLE=$(basename "$OLD_TARGET")
    
    if [[ "$BACKUP_OLD" == "true" ]]; then
        log_info "Backing up previous bundle: $OLD_BUNDLE"
        rm -f "$PREVIOUS_LINK"
        ln -sf "$OLD_BUNDLE" "$PREVIOUS_LINK"
    fi
fi

# Update current symlink
rm -f "$CURRENT_LINK"
ln -sf "$BUNDLE_ID" "$CURRENT_LINK"

log_success "Updated symlink: current -> $BUNDLE_ID"

# Step 6: Set permissions
log_info "Step 6: Setting permissions..."

chown -R root:root "$EXTRACT_PATH"
chmod -R 755 "$EXTRACT_PATH"
find "$EXTRACT_PATH" -type f -exec chmod 644 {} \;

# Ensure SELinux context if applicable
if command -v restorecon &>/dev/null; then
    restorecon -R "$EXTRACT_PATH" 2>/dev/null || true
fi

log_success "Permissions set"

# Step 7: Verify HTTPS access
if [[ "$VERIFY_HTTPS" == "true" ]]; then
    log_info "Step 7: Verifying HTTPS accessibility..."
    
    # Determine server hostname
    SERVER_HOST=$(hostname -f)
    REPO_URL="https://${SERVER_HOST}/repos/${OS_VERSION}/current/rpms/repodata/repomd.xml"
    
    if command -v curl &>/dev/null; then
        if curl -sk --head "$REPO_URL" | grep -q "200 OK"; then
            log_success "Repository accessible via HTTPS"
        else
            log_warn "Could not verify HTTPS access to: $REPO_URL"
            log_warn "Please verify your web server configuration"
        fi
    else
        log_warn "curl not available, skipping HTTPS verification"
    fi
else
    log_info "Step 7: Skipping HTTPS verification (--no-verify-https)"
fi

# Display summary
RPM_COUNT=$(find "${EXTRACT_PATH}/rpms" -name "*.rpm" | wc -l)
TOTAL_SIZE=$(du -sh "${EXTRACT_PATH}" | awk '{print $1}')

log_info ""
log_success "=========================================="
log_success "Bundle Import Complete"
log_success "=========================================="
log_info "Bundle:     $BUNDLE_ID"
log_info "Location:   $EXTRACT_PATH"
log_info "RPMs:       $RPM_COUNT packages"
log_info "Size:       $TOTAL_SIZE"
log_info ""
log_info "Repository Structure:"
log_info "  ${REPO_PATH}/"
log_info "  ├── current -> $BUNDLE_ID"
if [[ -L "$PREVIOUS_LINK" ]]; then
log_info "  ├── previous -> $(readlink "$PREVIOUS_LINK")"
fi
log_info "  └── $BUNDLE_ID/"
log_info "      ├── rpms/"
log_info "      │   └── repodata/"
log_info "      ├── manifests/"
log_info "      ├── metadata.json"
log_info "      └── SHA256SUMS"
log_info ""
log_info "Client Repository URL:"
log_info "  https://$(hostname -f)/repos/${OS_VERSION}/current/rpms"
log_success "=========================================="

log_script_end 0
