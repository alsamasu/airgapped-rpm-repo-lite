#!/bin/bash
# Common logging functions for airgapped-rpm-repo-lite

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Log levels
LOG_LEVEL="${LOG_LEVEL:-INFO}"

_log() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    case "$level" in
        ERROR)
            echo -e "${timestamp} [${RED}ERROR${NC}] ${message}" >&2
            ;;
        WARN)
            echo -e "${timestamp} [${YELLOW}WARN${NC}] ${message}" >&2
            ;;
        INFO)
            echo -e "${timestamp} [${BLUE}INFO${NC}] ${message}"
            ;;
        SUCCESS)
            echo -e "${timestamp} [${GREEN}OK${NC}] ${message}"
            ;;
        DEBUG)
            if [[ "$LOG_LEVEL" == "DEBUG" ]]; then
                echo -e "${timestamp} [DEBUG] ${message}"
            fi
            ;;
    esac
}

log_error() { _log ERROR "$1"; }
log_warn() { _log WARN "$1"; }
log_info() { _log INFO "$1"; }
log_success() { _log SUCCESS "$1"; }
log_debug() { _log DEBUG "$1"; }

# Die with error message
die() {
    log_error "$1"
    exit "${2:-1}"
}

# Check if command exists
require_command() {
    local cmd="$1"
    if ! command -v "$cmd" &> /dev/null; then
        die "Required command not found: $cmd"
    fi
}

# Verify running as root
require_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root"
    fi
}

# Log script start
log_script_start() {
    local script_name
    script_name=$(basename "$0")
    log_info "=========================================="
    log_info "Starting: ${script_name}"
    log_info "=========================================="
}

# Log script end
log_script_end() {
    local exit_code="${1:-0}"
    local script_name
    script_name=$(basename "$0")
    
    if [[ "$exit_code" -eq 0 ]]; then
        log_success "=========================================="
        log_success "Completed: ${script_name}"
        log_success "=========================================="
    else
        log_error "=========================================="
        log_error "Failed: ${script_name} (exit code: ${exit_code})"
        log_error "=========================================="
    fi
}
