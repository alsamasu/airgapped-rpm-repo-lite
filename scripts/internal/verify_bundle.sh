#!/bin/bash
# Verify bundle integrity without importing
#
# Usage:
#   ./verify_bundle.sh /path/to/bundle-rhel8-*.tar.zst

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common/logging.sh"
source "${SCRIPT_DIR}/../common/validation.sh"

BUNDLE_FILE="${1:-}"
CHECKSUM_FILE="${2:-}"

[[ -z "$BUNDLE_FILE" ]] && die "Usage: $(basename "$0") BUNDLE_FILE [CHECKSUM_FILE]"
[[ -f "$BUNDLE_FILE" ]] || die "Bundle file not found: $BUNDLE_FILE"

log_script_start

# Extract info from filename
BUNDLE_NAME=$(basename "$BUNDLE_FILE")
if [[ "$BUNDLE_NAME" =~ ^bundle-(rhel[89])-([0-9]{8}T[0-9]{6}Z)\.(tar\.(zst|gz))$ ]]; then
    OS_VERSION="${BASH_REMATCH[1]}"
    BUNDLE_ID="bundle-${OS_VERSION}-${BASH_REMATCH[2]}"
else
    die "Invalid bundle filename: $BUNDLE_NAME"
fi

log_info "Verifying bundle: $BUNDLE_ID"

# Find checksum file
if [[ -z "$CHECKSUM_FILE" ]]; then
    CHECKSUM_FILE="${BUNDLE_FILE%.tar.*}.sha256"
fi

# Verify checksum
if [[ -f "$CHECKSUM_FILE" ]]; then
    log_info "Checking SHA256 checksum..."
    EXPECTED=$(awk '{print $1}' "$CHECKSUM_FILE")
    ACTUAL=$(sha256sum "$BUNDLE_FILE" | awk '{print $1}')
    
    if [[ "$EXPECTED" == "$ACTUAL" ]]; then
        log_success "Checksum: VALID"
    else
        log_error "Checksum: MISMATCH"
        log_error "Expected: $EXPECTED"
        log_error "Actual:   $ACTUAL"
        exit 1
    fi
else
    log_warn "No checksum file found"
fi

# Verify archive integrity
log_info "Checking archive integrity..."
case "${BUNDLE_FILE##*.}" in
    zst)
        if zstd -t "$BUNDLE_FILE" 2>/dev/null; then
            log_success "Archive: VALID (zstd)"
        else
            log_error "Archive: CORRUPTED"
            exit 1
        fi
        ;;
    gz)
        if gzip -t "$BUNDLE_FILE" 2>/dev/null; then
            log_success "Archive: VALID (gzip)"
        else
            log_error "Archive: CORRUPTED"
            exit 1
        fi
        ;;
esac

# List contents
log_info "Bundle contents:"
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

case "${BUNDLE_FILE##*.}" in
    zst) zstd -d "$BUNDLE_FILE" -c | tar -tf - > "$TEMP_DIR/contents.txt" ;;
    gz)  tar -tzf "$BUNDLE_FILE" > "$TEMP_DIR/contents.txt" ;;
esac

RPM_COUNT=$(grep -c "\.rpm$" "$TEMP_DIR/contents.txt" || echo 0)
MANIFEST_COUNT=$(grep -c "manifests/.*\.json$" "$TEMP_DIR/contents.txt" || echo 0)

log_info "  RPMs:      $RPM_COUNT"
log_info "  Manifests: $MANIFEST_COUNT"

# Check for required files
HAS_METADATA=$(grep -c "metadata.json$" "$TEMP_DIR/contents.txt" || echo 0)
HAS_REPODATA=$(grep -c "repodata/repomd.xml$" "$TEMP_DIR/contents.txt" || echo 0)

if [[ "$HAS_METADATA" -gt 0 ]]; then
    log_success "  metadata.json: PRESENT"
else
    log_warn "  metadata.json: MISSING"
fi

if [[ "$HAS_REPODATA" -gt 0 ]]; then
    log_success "  repodata: PRESENT"
else
    log_warn "  repodata: MISSING (will be regenerated on import)"
fi

log_success "Bundle verification complete: $BUNDLE_ID"
log_script_end 0
