#!/bin/bash
# End-to-End Test for airgapped-rpm-repo-lite
#
# This script runs a complete E2E test cycle:
# 1. Collect manifests from test VMs
# 2. Build bundles on external builders
# 3. Import bundles on internal servers
# 4. Patch test hosts
# 5. Verify results and generate evidence
#
# Usage:
#   ./e2e_test.sh [--skip-build] [--skip-import] [--evidence-dir DIR]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Source common functions
source "${REPO_ROOT}/scripts/common/logging.sh"

# Configuration
EVIDENCE_DIR="${SCRIPT_DIR}/artifacts/e2e-lite-proof"
ANSIBLE_DIR="${REPO_ROOT}/ansible"
INVENTORY="${ANSIBLE_DIR}/inventories/e2e_hosts.yml"
MANIFEST_DIR="${EVIDENCE_DIR}/manifests"
BUNDLE_DIR="${EVIDENCE_DIR}/bundles"

# Test options
SKIP_BUILD=false
SKIP_IMPORT=false
SKIP_PATCH=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-import)
            SKIP_IMPORT=true
            shift
            ;;
        --skip-patch)
            SKIP_PATCH=true
            shift
            ;;
        --evidence-dir)
            EVIDENCE_DIR="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Initialize
log_script_start
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
TEST_ID="e2e-${TIMESTAMP}"

log_info "Test ID: $TEST_ID"
log_info "Evidence directory: $EVIDENCE_DIR"

# Create evidence directories
mkdir -p "${EVIDENCE_DIR}"/{manifests,bundles,patch-logs,reports}
mkdir -p "${MANIFEST_DIR}"

# Initialize truth table
TRUTH_TABLE="${EVIDENCE_DIR}/truth-table.json"
cat > "$TRUTH_TABLE" <<EOF
{
  "test_id": "$TEST_ID",
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "tests": {}
}
EOF

# Helper to update truth table
update_truth_table() {
    local test_name="$1"
    local status="$2"
    local details="${3:-}"
    
    python3 -c "
import json
with open('$TRUTH_TABLE', 'r+') as f:
    data = json.load(f)
    data['tests']['$test_name'] = {
        'status': '$status',
        'details': '$details',
        'timestamp': '$(date -u +"%Y-%m-%dT%H:%M:%SZ")'
    }
    f.seek(0)
    json.dump(data, f, indent=2)
    f.truncate()
"
}

#####################################################################
# Phase 1: Manifest Collection
#####################################################################

log_info ""
log_info "=========================================="
log_info "Phase 1: Manifest Collection"
log_info "=========================================="

cd "$ANSIBLE_DIR"

if ansible-playbook -i "$INVENTORY" playbooks/collect_manifests.yml \
    -e "manifest_local_dir=${MANIFEST_DIR}" 2>&1 | tee "${EVIDENCE_DIR}/manifest-collection.log"; then
    
    MANIFEST_COUNT=$(find "$MANIFEST_DIR" -name "*.json" | wc -l)
    log_success "Collected $MANIFEST_COUNT manifests"
    update_truth_table "manifest_collection" "PASS" "Collected $MANIFEST_COUNT manifests"
else
    log_error "Manifest collection failed"
    update_truth_table "manifest_collection" "FAIL" "Ansible playbook failed"
    exit 1
fi

# Copy manifests to evidence
cp -r "$MANIFEST_DIR"/*.json "${EVIDENCE_DIR}/manifests/" 2>/dev/null || true

# Generate manifest summary
python3 -c "
import json
from pathlib import Path

manifest_dir = Path('$MANIFEST_DIR')
summary = {'manifests': []}

for mf in manifest_dir.glob('*.json'):
    with open(mf) as f:
        m = json.load(f)
    summary['manifests'].append({
        'host_id': m.get('host_id'),
        'os_major': m.get('os', {}).get('major'),
        'os_minor': m.get('os', {}).get('minor'),
        'package_count': len(m.get('installed_rpms', []))
    })

with open('${EVIDENCE_DIR}/manifest-summary.json', 'w') as f:
    json.dump(summary, f, indent=2)
"

#####################################################################
# Phase 2: Bundle Building (on external builders)
#####################################################################

if [[ "$SKIP_BUILD" == "true" ]]; then
    log_info ""
    log_info "=========================================="
    log_info "Phase 2: Bundle Building (SKIPPED)"
    log_info "=========================================="
    update_truth_table "bundle_build_rhel8" "BLOCKED" "Skipped by user"
    update_truth_table "bundle_build_rhel9" "BLOCKED" "Skipped by user"
else
    log_info ""
    log_info "=========================================="
    log_info "Phase 2: Bundle Building"
    log_info "=========================================="
    
    mkdir -p "$BUNDLE_DIR"
    
    # Build RHEL 8 bundle
    log_info "Building RHEL 8 bundle..."
    
    # Copy manifests to ext-rhel8 and build
    if ssh ext-rhel8 "mkdir -p /tmp/e2e-manifests" && \
       scp "${MANIFEST_DIR}"/*.json ext-rhel8:/tmp/e2e-manifests/ && \
       ssh ext-rhel8 "cd /opt/airgapped-rpm-repo-lite && \
           ./scripts/external/build_bundle.sh \
               --manifests /tmp/e2e-manifests \
               --os rhel8 \
               --output /tmp/e2e-bundles" 2>&1 | tee "${EVIDENCE_DIR}/bundle-build-rhel8.log"; then
        
        # Copy bundle back
        scp ext-rhel8:/tmp/e2e-bundles/bundle-rhel8-*.tar.* "$BUNDLE_DIR/" 2>/dev/null || true
        scp ext-rhel8:/tmp/e2e-bundles/bundle-rhel8-*.sha256 "$BUNDLE_DIR/" 2>/dev/null || true
        
        log_success "RHEL 8 bundle built"
        update_truth_table "bundle_build_rhel8" "PASS"
    else
        log_error "RHEL 8 bundle build failed"
        update_truth_table "bundle_build_rhel8" "FAIL"
    fi
    
    # Build RHEL 9 bundle
    log_info "Building RHEL 9 bundle..."
    
    if ssh ext-rhel9 "mkdir -p /tmp/e2e-manifests" && \
       scp "${MANIFEST_DIR}"/*.json ext-rhel9:/tmp/e2e-manifests/ && \
       ssh ext-rhel9 "cd /opt/airgapped-rpm-repo-lite && \
           ./scripts/external/build_bundle.sh \
               --manifests /tmp/e2e-manifests \
               --os rhel9 \
               --output /tmp/e2e-bundles" 2>&1 | tee "${EVIDENCE_DIR}/bundle-build-rhel9.log"; then
        
        scp ext-rhel9:/tmp/e2e-bundles/bundle-rhel9-*.tar.* "$BUNDLE_DIR/" 2>/dev/null || true
        scp ext-rhel9:/tmp/e2e-bundles/bundle-rhel9-*.sha256 "$BUNDLE_DIR/" 2>/dev/null || true
        
        log_success "RHEL 9 bundle built"
        update_truth_table "bundle_build_rhel9" "PASS"
    else
        log_error "RHEL 9 bundle build failed"
        update_truth_table "bundle_build_rhel9" "FAIL"
    fi
    
    # Record bundle sizes
    ls -lh "$BUNDLE_DIR"/*.tar.* 2>/dev/null > "${EVIDENCE_DIR}/bundle-sizes.txt" || true
fi

#####################################################################
# Phase 3: Bundle Import (on internal servers)
#####################################################################

if [[ "$SKIP_IMPORT" == "true" ]]; then
    log_info ""
    log_info "=========================================="
    log_info "Phase 3: Bundle Import (SKIPPED)"
    log_info "=========================================="
    update_truth_table "bundle_import_rhel8" "BLOCKED" "Skipped by user"
    update_truth_table "bundle_import_rhel9" "BLOCKED" "Skipped by user"
else
    log_info ""
    log_info "=========================================="
    log_info "Phase 3: Bundle Import"
    log_info "=========================================="
    
    # Import RHEL 8 bundle
    RHEL8_BUNDLE=$(ls "$BUNDLE_DIR"/bundle-rhel8-*.tar.* 2>/dev/null | head -1 || true)
    
    if [[ -n "$RHEL8_BUNDLE" ]]; then
        log_info "Importing RHEL 8 bundle to int-rhel8..."
        
        if scp "$RHEL8_BUNDLE" "${RHEL8_BUNDLE%.tar.*}.sha256" int-rhel8:/tmp/ && \
           ssh int-rhel8 "cd /opt/airgapped-rpm-repo-lite && \
               ./scripts/internal/import_bundle.sh /tmp/$(basename "$RHEL8_BUNDLE")" \
               2>&1 | tee "${EVIDENCE_DIR}/bundle-import-rhel8.log"; then
            
            log_success "RHEL 8 bundle imported"
            update_truth_table "bundle_import_rhel8" "PASS"
        else
            log_error "RHEL 8 bundle import failed"
            update_truth_table "bundle_import_rhel8" "FAIL"
        fi
    else
        log_warn "No RHEL 8 bundle found to import"
        update_truth_table "bundle_import_rhel8" "BLOCKED" "No bundle available"
    fi
    
    # Import RHEL 9 bundle
    RHEL9_BUNDLE=$(ls "$BUNDLE_DIR"/bundle-rhel9-*.tar.* 2>/dev/null | head -1 || true)
    
    if [[ -n "$RHEL9_BUNDLE" ]]; then
        log_info "Importing RHEL 9 bundle to int-rhel9..."
        
        if scp "$RHEL9_BUNDLE" "${RHEL9_BUNDLE%.tar.*}.sha256" int-rhel9:/tmp/ && \
           ssh int-rhel9 "cd /opt/airgapped-rpm-repo-lite && \
               ./scripts/internal/import_bundle.sh /tmp/$(basename "$RHEL9_BUNDLE")" \
               2>&1 | tee "${EVIDENCE_DIR}/bundle-import-rhel9.log"; then
            
            log_success "RHEL 9 bundle imported"
            update_truth_table "bundle_import_rhel9" "PASS"
        else
            log_error "RHEL 9 bundle import failed"
            update_truth_table "bundle_import_rhel9" "FAIL"
        fi
    else
        log_warn "No RHEL 9 bundle found to import"
        update_truth_table "bundle_import_rhel9" "BLOCKED" "No bundle available"
    fi
fi

#####################################################################
# Phase 4: Host Patching
#####################################################################

if [[ "$SKIP_PATCH" == "true" ]]; then
    log_info ""
    log_info "=========================================="
    log_info "Phase 4: Host Patching (SKIPPED)"
    log_info "=========================================="
    update_truth_table "patch_rhel8_tester" "BLOCKED" "Skipped by user"
    update_truth_table "patch_rhel9_tester" "BLOCKED" "Skipped by user"
else
    log_info ""
    log_info "=========================================="
    log_info "Phase 4: Host Patching"
    log_info "=========================================="
    
    cd "$ANSIBLE_DIR"
    
    if ansible-playbook -i "$INVENTORY" playbooks/patch_hosts.yml \
        -l testers \
        -e "evidence_dir=${EVIDENCE_DIR}/patch-logs" \
        2>&1 | tee "${EVIDENCE_DIR}/patch-hosts.log"; then
        
        log_success "Host patching completed"
        update_truth_table "patch_rhel8_tester" "PASS"
        update_truth_table "patch_rhel9_tester" "PASS"
    else
        log_error "Host patching failed"
        update_truth_table "patch_rhel8_tester" "FAIL"
        update_truth_table "patch_rhel9_tester" "FAIL"
    fi
fi

#####################################################################
# Phase 5: Verification and Evidence Collection
#####################################################################

log_info ""
log_info "=========================================="
log_info "Phase 5: Verification"
log_info "=========================================="

# Collect post-patch verification
for host in rhel8-10-tester rhel9-6-tester; do
    log_info "Verifying $host..."
    
    ssh "$host" "
        echo '=== Kernel ==='
        uname -r
        echo ''
        echo '=== OS Release ==='
        cat /etc/os-release | grep -E '^(NAME|VERSION)'
        echo ''
        echo '=== Package Count ==='
        rpm -qa | wc -l
        echo ''
        echo '=== Recent DNF History ==='
        dnf history list --last 3
    " > "${EVIDENCE_DIR}/verification-${host}.txt" 2>&1 || true
done

# Generate final report
log_info "Generating final report..."

python3 -c "
import json
from pathlib import Path

evidence_dir = Path('$EVIDENCE_DIR')
truth_table = json.load(open('$TRUTH_TABLE'))

# Count results
tests = truth_table.get('tests', {})
passed = len([t for t in tests.values() if t.get('status') == 'PASS'])
failed = len([t for t in tests.values() if t.get('status') == 'FAIL'])
blocked = len([t for t in tests.values() if t.get('status') == 'BLOCKED'])

# Generate report
report = {
    'test_id': truth_table.get('test_id'),
    'timestamp': truth_table.get('timestamp'),
    'summary': {
        'total': len(tests),
        'passed': passed,
        'failed': failed,
        'blocked': blocked,
        'pass_rate': f'{(passed / len(tests) * 100):.1f}%' if tests else 'N/A'
    },
    'tests': tests,
    'evidence_files': [str(f.name) for f in evidence_dir.glob('*') if f.is_file()]
}

with open(evidence_dir / 'final-report.json', 'w') as f:
    json.dump(report, f, indent=2)

# Print summary
print(f'''
E2E Test Summary
================
Test ID: {report['test_id']}
Total:   {report['summary']['total']}
Passed:  {report['summary']['passed']}
Failed:  {report['summary']['failed']}
Blocked: {report['summary']['blocked']}
Pass Rate: {report['summary']['pass_rate']}
''')
"

log_info ""
log_success "=========================================="
log_success "E2E Test Complete"
log_success "=========================================="
log_info "Evidence location: $EVIDENCE_DIR"
log_info "Truth table: $TRUTH_TABLE"
log_info "Final report: ${EVIDENCE_DIR}/final-report.json"

log_script_end 0
