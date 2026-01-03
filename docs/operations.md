# Operations Guide

This guide covers the monthly patching workflow for the airgapped-rpm-repo-lite system.

## Monthly Patching Workflow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         MONTHLY PATCHING CYCLE                                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  Week 1: Preparation                                                          │
│  ─────────────────────                                                        │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                       │
│  │  Collect    │───▶│   Review    │───▶│   Plan      │                       │
│  │  Manifests  │    │   Updates   │    │   Schedule  │                       │
│  └─────────────┘    └─────────────┘    └─────────────┘                       │
│                                                                               │
│  Week 2: Build & Transfer                                                     │
│  ────────────────────────                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                       │
│  │   Build     │───▶│  Transfer   │───▶│   Import    │                       │
│  │   Bundles   │    │  (Air Gap)  │    │   Bundles   │                       │
│  └─────────────┘    └─────────────┘    └─────────────┘                       │
│                                                                               │
│  Week 3-4: Patching                                                           │
│  ──────────────────                                                           │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                       │
│  │   Patch     │───▶│   Verify    │───▶│   Document  │                       │
│  │   Hosts     │    │   Results   │    │   Evidence  │                       │
│  └─────────────┘    └─────────────┘    └─────────────┘                       │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Step-by-Step Procedures

### Phase 1: Manifest Collection

**When:** First week of the month

**Who:** System Administrator with Ansible access

**Procedure:**

1. Connect to Ansible control node
2. Run manifest collection playbook:

```bash
cd /opt/airgapped-rpm-repo-lite/ansible

# Collect manifests from all hosts
ansible-playbook -i inventories/hosts.yml playbooks/collect_manifests.yml
```

3. Review collected manifests:

```bash
# Count manifests by OS version
for f in artifacts/manifests/*.json; do
    os_major=$(python3 -c "import json; print(json.load(open('$f'))['os']['major'])")
    echo "$f: RHEL $os_major"
done | sort | uniq -c
```

4. Prepare manifests for transfer to external builders:

```bash
# Create manifest package
cd artifacts/manifests
tar -czf manifests-$(date +%Y%m).tar.gz *.json

# Verify package
tar -tzf manifests-$(date +%Y%m).tar.gz
```

### Phase 2: Bundle Building

**When:** Week 2, after receiving manifests

**Who:** Operator with access to external builders

**Procedure on ext-rhel8:**

1. Receive manifest package via approved transfer method
2. Extract manifests:

```bash
mkdir -p /var/lib/rpm-manifests/$(date +%Y%m)
tar -xzf manifests-*.tar.gz -C /var/lib/rpm-manifests/$(date +%Y%m)/
```

3. Build RHEL 8 bundle:

```bash
cd /opt/airgapped-rpm-repo-lite

./scripts/external/build_bundle.sh \
    --manifests /var/lib/rpm-manifests/$(date +%Y%m) \
    --os rhel8 \
    --output /var/lib/rpm-bundles
```

4. Verify bundle:

```bash
ls -lh /var/lib/rpm-bundles/bundle-rhel8-*.tar.zst
cat /var/lib/rpm-bundles/bundle-rhel8-*.sha256
```

**Procedure on ext-rhel9:**

Repeat the same steps for RHEL 9.

### Phase 3: Bundle Transfer

**When:** Week 2, after bundles are built

**Who:** Security Officer or designated transfer personnel

**Procedure:**

1. Copy bundles to approved transfer media:

```bash
# On external network
cp /var/lib/rpm-bundles/bundle-rhel8-*.tar.zst /media/transfer/
cp /var/lib/rpm-bundles/bundle-rhel8-*.sha256 /media/transfer/
cp /var/lib/rpm-bundles/bundle-rhel9-*.tar.zst /media/transfer/
cp /var/lib/rpm-bundles/bundle-rhel9-*.sha256 /media/transfer/
```

2. Verify checksums before transfer:

```bash
cd /media/transfer
sha256sum -c bundle-*.sha256
```

3. Transfer media across air gap per security procedures

4. Verify checksums after transfer:

```bash
# On internal network
cd /media/transfer
sha256sum -c bundle-*.sha256
```

### Phase 4: Bundle Import

**When:** Week 2, after transfer verification

**Who:** System Administrator with access to internal servers

**Procedure on int-rhel8:**

1. Import bundle:

```bash
cd /opt/airgapped-rpm-repo-lite

./scripts/internal/import_bundle.sh /media/transfer/bundle-rhel8-*.tar.zst
```

2. Verify repository:

```bash
./scripts/internal/publish_repos.sh --verify
```

**Procedure on int-rhel9:**

Repeat the same steps for RHEL 9.

### Phase 5: Host Patching

**When:** Weeks 3-4, during maintenance windows

**Who:** System Administrator with Ansible access

**Procedure:**

1. Pre-patch checks:

```bash
# Verify repository accessibility
ansible all -i inventories/hosts.yml -m command -a "dnf repolist"

# Check available updates
ansible all -i inventories/hosts.yml -m command -a "dnf check-update" || true
```

2. Patch hosts (by group):

```bash
# Patch RHEL 8 hosts
ansible-playbook -i inventories/hosts.yml playbooks/patch_hosts.yml \
    -l rhel8_hosts \
    --check  # Dry run first

ansible-playbook -i inventories/hosts.yml playbooks/patch_hosts.yml \
    -l rhel8_hosts

# Patch RHEL 9 hosts
ansible-playbook -i inventories/hosts.yml playbooks/patch_hosts.yml \
    -l rhel9_hosts
```

3. Collect patch evidence:

```bash
# Evidence is automatically saved to artifacts/patch-evidence/
ls -la ansible/artifacts/patch-evidence/
```

### Phase 6: Verification and Documentation

**When:** After patching completes

**Who:** System Administrator

**Procedure:**

1. Review patch reports:

```bash
for report in ansible/artifacts/patch-evidence/*-patch-report.json; do
    echo "=== $(basename $report) ==="
    python3 -c "import json; r=json.load(open('$report')); print(f\"Kernel: {r['pre_kernel']} -> {r['post_kernel']}\")"
done
```

2. Generate summary report:

```bash
python3 -c "
import json
from pathlib import Path

reports = []
for f in Path('ansible/artifacts/patch-evidence').glob('*-patch-report.json'):
    reports.append(json.load(open(f)))

print(f'Total hosts patched: {len(reports)}')
print(f'Reboots required: {sum(1 for r in reports if r[\"rebooted\"])}')
print(f'Kernel updates: {sum(1 for r in reports if r[\"kernel_changed\"])}')
"
```

3. Archive evidence:

```bash
# Create monthly evidence archive
cd ansible/artifacts
tar -czf patch-evidence-$(date +%Y%m).tar.gz patch-evidence/

# Move to permanent storage
mv patch-evidence-$(date +%Y%m).tar.gz /var/log/patching/
```

## Rollback Procedures

### Reverting to Previous Bundle

If issues are discovered after patching:

1. Switch repository to previous bundle:

```bash
# On internal server
cd /var/www/html/repos/rhel8
rm current
ln -s $(readlink previous) current
```

2. On affected hosts, downgrade packages:

```bash
# Identify changed packages
diff pre-patch-packages.txt post-patch-packages.txt

# Downgrade specific package
dnf downgrade package-name
```

### Emergency Procedures

**If internal server is unavailable:**

1. Boot hosts from local recovery media
2. Mount backup repository from USB
3. Configure temporary local repository

## Monitoring and Alerting

### Health Checks

Run weekly:

```bash
# Check repository status
./scripts/internal/publish_repos.sh --status

# Verify repository accessibility
curl -sk https://int-rhel8.internal/repos/rhel8/current/rpms/repodata/repomd.xml | head -5
```

### Log Locations

- Build logs: `/var/lib/rpm-bundles/bundle-*/build.log`
- Import logs: `/var/log/rpm-repo/import.log`
- Patch logs: `ansible/artifacts/patch-evidence/`

## Maintenance Tasks

### Disk Space Management

Remove old bundles after successful patching:

```bash
# List bundles by date
ls -lt /var/www/html/repos/rhel8/bundle-*

# Keep last 3 bundles, remove older
cd /var/www/html/repos/rhel8
ls -t bundle-* | tail -n +4 | xargs rm -rf
```

### Certificate Renewal

Before TLS certificates expire:

```bash
# Check expiration
openssl x509 -enddate -noout -in /etc/pki/tls/certs/int-rhel8.crt

# Regenerate if needed (see deployment.md)
```
