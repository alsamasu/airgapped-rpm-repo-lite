#!/bin/bash
# Validation functions for airgapped-rpm-repo-lite

# Source logging if not already loaded
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${_LOG_LOADED:-}" ]]; then
    source "${SCRIPT_DIR}/logging.sh"
    _LOG_LOADED=1
fi

# Validate OS version
validate_os_version() {
    local expected_major="$1"
    
    if [[ ! -f /etc/os-release ]]; then
        die "Cannot determine OS version: /etc/os-release not found"
    fi
    
    local actual_major
    actual_major=$(grep VERSION_ID /etc/os-release | cut -d'"' -f2 | cut -d'.' -f1)
    
    if [[ "$actual_major" != "$expected_major" ]]; then
        die "OS version mismatch: expected RHEL ${expected_major}, got RHEL ${actual_major}"
    fi
    
    log_info "OS version verified: RHEL ${actual_major}"
}

# Validate subscription status
validate_subscription() {
    if ! subscription-manager status &>/dev/null; then
        log_warn "System is not registered with subscription-manager"
        return 1
    fi
    log_info "Subscription status: Active"
    return 0
}

# Validate required repos are enabled
validate_repos() {
    local missing_repos=()
    
    for repo in "$@"; do
        if ! dnf repolist --enabled | grep -q "$repo"; then
            missing_repos+=("$repo")
        fi
    done
    
    if [[ ${#missing_repos[@]} -gt 0 ]]; then
        log_error "Missing required repositories: ${missing_repos[*]}"
        return 1
    fi
    
    log_info "All required repositories are enabled"
    return 0
}

# Validate manifest file
validate_manifest() {
    local manifest_file="$1"
    
    if [[ ! -f "$manifest_file" ]]; then
        log_error "Manifest file not found: $manifest_file"
        return 1
    fi
    
    # Check if it's valid JSON
    if ! python3 -c "import json; json.load(open('$manifest_file'))" 2>/dev/null; then
        log_error "Invalid JSON in manifest: $manifest_file"
        return 1
    fi
    
    # Check required fields
    local required_fields=("schema_version" "host_id" "os" "installed_rpms")
    for field in "${required_fields[@]}"; do
        if ! python3 -c "import json; m=json.load(open('$manifest_file')); assert '$field' in m" 2>/dev/null; then
            log_error "Missing required field '$field' in manifest: $manifest_file"
            return 1
        fi
    done
    
    log_debug "Manifest validated: $manifest_file"
    return 0
}

# Validate bundle file
validate_bundle() {
    local bundle_file="$1"
    local checksum_file="${2:-}"
    
    if [[ ! -f "$bundle_file" ]]; then
        log_error "Bundle file not found: $bundle_file"
        return 1
    fi
    
    # Verify checksum if provided
    if [[ -n "$checksum_file" && -f "$checksum_file" ]]; then
        local expected_hash
        expected_hash=$(grep "$(basename "$bundle_file")" "$checksum_file" | awk '{print $1}')
        
        if [[ -n "$expected_hash" ]]; then
            local actual_hash
            actual_hash=$(sha256sum "$bundle_file" | awk '{print $1}')
            
            if [[ "$expected_hash" != "$actual_hash" ]]; then
                log_error "Checksum mismatch for $bundle_file"
                log_error "Expected: $expected_hash"
                log_error "Actual:   $actual_hash"
                return 1
            fi
            log_info "Checksum verified: $bundle_file"
        fi
    fi
    
    # Verify archive integrity
    local bundle_ext="${bundle_file##*.}"
    case "$bundle_ext" in
        zst)
            if ! zstd -t "$bundle_file" 2>/dev/null; then
                log_error "Bundle archive is corrupted: $bundle_file"
                return 1
            fi
            ;;
        gz)
            if ! gzip -t "$bundle_file" 2>/dev/null; then
                log_error "Bundle archive is corrupted: $bundle_file"
                return 1
            fi
            ;;
    esac
    
    log_info "Bundle validated: $bundle_file"
    return 0
}

# Validate directory exists and is writable
validate_directory() {
    local dir="$1"
    local create="${2:-false}"
    
    if [[ ! -d "$dir" ]]; then
        if [[ "$create" == "true" ]]; then
            mkdir -p "$dir" || die "Failed to create directory: $dir"
            log_info "Created directory: $dir"
        else
            log_error "Directory does not exist: $dir"
            return 1
        fi
    fi
    
    if [[ ! -w "$dir" ]]; then
        log_error "Directory is not writable: $dir"
        return 1
    fi
    
    return 0
}

# Get disk space in GB
get_available_space() {
    local path="$1"
    df -BG "$path" | tail -1 | awk '{print $4}' | tr -d 'G'
}

# Check minimum disk space
require_disk_space() {
    local path="$1"
    local required_gb="$2"
    
    local available
    available=$(get_available_space "$path")
    
    if [[ "$available" -lt "$required_gb" ]]; then
        die "Insufficient disk space at $path: ${available}GB available, ${required_gb}GB required"
    fi
    
    log_info "Disk space check passed: ${available}GB available at $path"
}
