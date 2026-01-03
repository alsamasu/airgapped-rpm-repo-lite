#!/bin/bash
# Install Python dependencies on RHEL external/internal servers
#
# This script is for RHEL 8/9 servers ONLY.
# Windows operator machines do NOT require Python.
#
# Usage:
#   ./install_python_deps.sh
#
# Prerequisites:
#   - RHEL 8.x or 9.x
#   - Root or sudo access
#   - For external builders: active Red Hat subscription

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# Check we're on RHEL
if [[ ! -f /etc/redhat-release ]]; then
    log_error "This script is for RHEL systems only"
    exit 1
fi

# Get OS version
OS_VERSION=$(grep -oP '(?<=release )\d+' /etc/redhat-release)
log_info "Detected RHEL ${OS_VERSION}"

# Check root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

log_info "Installing Python dependencies for airgapped-rpm-repo-lite..."

# Install Python 3 and pip
log_info "Installing Python 3..."
dnf install -y python3 python3-pip python3-setuptools

# Install required system packages
log_info "Installing system packages..."
dnf install -y \
    createrepo_c \
    zstd \
    git \
    rsync \
    httpd \
    mod_ssl

# Verify Python version
PYTHON_VERSION=$(python3 --version)
log_info "Python version: ${PYTHON_VERSION}"

# Install Python packages (minimal - only what's needed for manifest tools)
log_info "Installing Python packages..."

# For RHEL 8, we may need to use pip with --user or system packages
if [[ "$OS_VERSION" == "8" ]]; then
    # RHEL 8 - use dnf where possible
    dnf install -y python3-pyyaml python3-requests || true
    pip3 install --quiet jsonschema || true
elif [[ "$OS_VERSION" == "9" ]]; then
    # RHEL 9 - use dnf where possible  
    dnf install -y python3-pyyaml python3-requests || true
    pip3 install --quiet jsonschema || true
fi

# Verify the airgapped-rpm-repo-lite Python modules can be imported
log_info "Verifying Python modules..."
if python3 -c "import sys; sys.path.insert(0, '${REPO_ROOT}'); from src.manifest_tools import ManifestCollector, ManifestMerger, ManifestValidator" 2>/dev/null; then
    log_info "Python modules verified successfully"
else
    log_warn "Python modules not yet installed - this is expected on first run"
fi

# Set up PYTHONPATH for the repo
PROFILE_FILE="/etc/profile.d/airgapped-rpm-repo-lite.sh"
cat > "$PROFILE_FILE" << EOF
# airgapped-rpm-repo-lite Python path
export PYTHONPATH="${REPO_ROOT}:\${PYTHONPATH:-}"
export PATH="${REPO_ROOT}/scripts/external:${REPO_ROOT}/scripts/internal:\${PATH}"
EOF

log_info "Created ${PROFILE_FILE}"

# Summary
log_info ""
log_info "=========================================="
log_info "Python Dependencies Installed"
log_info "=========================================="
log_info "Python: $(python3 --version)"
log_info "Pip: $(pip3 --version 2>/dev/null || echo 'not available')"
log_info ""
log_info "System packages installed:"
log_info "  - createrepo_c"
log_info "  - zstd"
log_info "  - git"
log_info "  - httpd + mod_ssl"
log_info ""
log_info "To activate paths, run: source ${PROFILE_FILE}"
log_info "Or log out and back in."
log_info "=========================================="
