# Caveats and Tradeoffs

This document explicitly describes the tradeoffs of using airgapped-rpm-repo-lite
compared to Foreman/Katello/Satellite solutions.

## Executive Summary

| Aspect | Policy B (This System) | Foreman/Katello |
|--------|------------------------|-----------------|
| Bundle Size | GBs per cycle | TBs total |
| Monthly Effort | Hours | Days |
| Infrastructure | 4 VMs | 10+ VMs |
| Errata Tracking | No | Yes |
| Content Views | No | Yes |
| Lifecycle Envs | No | Yes |
| Compliance Reports | Limited | Full |

## What You Lose

### 1. Errata Lifecycle Semantics

**Foreman/Katello provides:**
- Named errata (RHSA-2024:1234)
- Errata classification (Security/Bugfix/Enhancement)
- CVE mapping
- Errata dependencies
- Publication dates

**This system provides:**
- Package updates only
- Security flag on packages (when available)
- No formal errata tracking
- No CVE database integration

**Impact:**
- Cannot report "We applied RHSA-2024:1234 on date X"
- Must track compliance by package version, not errata ID
- Audit evidence is package-based, not errata-based

**Mitigation:**
- Bundle metadata includes advisory IDs when available from DNF
- Pre/post package diffs provide clear change evidence
- Security updates are prioritized in dependency resolution

### 2. Content Views

**Foreman/Katello provides:**
- Named, versioned content views
- Selective package inclusion/exclusion
- Composite views
- Version history

**This system provides:**
- Single "current" repository
- No version history beyond previous symlink
- No package filtering

**Impact:**
- Cannot maintain multiple package sets for different environments
- Cannot selectively exclude packages
- All hosts get same package versions

**Mitigation:**
- Use OS major version separation (rhel8 vs rhel9)
- Archive bundles for historical reference
- Manifest traceability shows what each host needs

### 3. Lifecycle Environments

**Foreman/Katello provides:**
- Dev → Test → Stage → Prod promotion
- Environment-specific content
- Gated deployments
- Rollback to previous environment state

**This system provides:**
- Single "current" repository per OS
- Manual rollback via previous symlink
- No environment separation

**Impact:**
- Cannot test patches in dev before prod
- No gradual rollout capability
- All hosts patch from same repository

**Mitigation:**
- Use host groups in Ansible for staged rollouts
- Manual testing on representative hosts before full deployment
- Maintain previous bundle for emergency rollback

### 4. Full Repository Mirroring

**Foreman/Katello provides:**
- Complete repository mirrors
- Install any package from Red Hat
- Historical package versions
- Debug and source packages

**This system provides:**
- Only packages needed for installed software
- Only latest versions
- No debug/source packages

**Impact:**
- Cannot install new software from repository
- Cannot access older package versions
- Cannot debug with -debuginfo packages

**Mitigation:**
- Maintain separate "base install" repository for new software
- Request specific packages in manifest if needed
- Use external network for one-off installs, then collect manifest

### 5. Compliance Reporting

**Foreman/Katello provides:**
- Errata compliance reports
- Host subscription status
- Package deviation reports
- Dashboard views

**This system provides:**
- Manifest-based package lists
- Pre/post patch diffs
- Manual compliance checking

**Impact:**
- No built-in compliance dashboard
- Manual audit evidence collection
- Limited subscription tracking

**Mitigation:**
- Use Ansible facts for inventory
- Generate reports from manifests
- Integrate with external compliance tools

## What You Gain

### 1. Smaller Bundle Sizes

**Typical sizes:**
- Full RHEL 8 BaseOS+AppStream: ~30GB
- Policy B bundle: 500MB - 2GB

**Savings:**
- 90%+ reduction in transfer size
- Faster air gap transfers
- Less storage on internal servers

### 2. Faster Monthly Cycles

**Foreman/Katello workflow:**
- Sync repositories (hours)
- Create content view version (minutes)
- Publish and promote (minutes each env)
- Export and transfer (hours for large repos)
- Import (hours)

**This system workflow:**
- Collect manifests (minutes)
- Build bundle (30-60 minutes)
- Transfer bundle (minutes)
- Import bundle (minutes)

**Total time reduction:** Days → Hours

### 3. Simpler Infrastructure

**Foreman/Katello requires:**
- Satellite server (large VM)
- Capsule servers (per network segment)
- PostgreSQL database
- Pulp content storage
- MongoDB (older versions)

**This system requires:**
- 2 external builders (minimal VMs)
- 2 internal repo servers (minimal VMs)
- No databases

**Reduction:** 10+ VMs → 4 VMs

### 4. Lower Operational Overhead

**Eliminated tasks:**
- Satellite upgrades
- Content view management
- Lifecycle environment design
- Subscription allocation
- Capsule synchronization

**Remaining tasks:**
- Monthly bundle build/transfer
- Ansible playbook execution
- Certificate management

### 5. Predictable Behavior

**No surprises from:**
- Content view filter bugs
- Errata dependency issues
- Capsule sync failures
- Hammer CLI quirks

**Predictable because:**
- DNF resolves dependencies directly
- Bundle contains exactly what's needed
- Simple file-based transfer

## When to Choose This System

### Good Fit

- Small to medium environments (< 500 hosts)
- Monthly patch cycles are acceptable
- Package-level tracking is sufficient
- Limited infrastructure budget
- Simple compliance requirements

### Poor Fit

- Large environments (> 1000 hosts)
- Continuous patching required
- Errata-level compliance mandated
- Multiple environment promotions needed
- Full repository access required

## Hybrid Approaches

### Option 1: Policy B for Monthly, Satellite for Emergency

Use this system for routine monthly patching, maintain minimal Satellite
for emergency CVE patches requiring immediate deployment.

### Option 2: Policy B Internal, Full Mirror External

Use full repository sync on external network for flexibility, use Policy B
bundles for efficient air gap transfer.

### Option 3: Gradual Migration

Start with Policy B for new environments, gradually migrate existing
Satellite-managed hosts as lifecycle needs are evaluated.

## Technical Limitations

### Package Selection

- Only packages installed on at least one host are included
- New package installs require manifest update and rebuild
- Dependency resolution uses builder's repository state

### Version Pinning

- Cannot pin to specific package versions
- Always gets latest available version
- No version ranges or constraints

### Repository Features

- No module support (DNF modules)
- No group package support (@groups)
- No weak dependencies handling

### Manifest Accuracy

- Manifest reflects point-in-time state
- Interim package changes not captured
- Manual installs may be missed

## Recommendations

### For Successful Adoption

1. **Set expectations:** This is not Satellite replacement, it's an alternative approach
2. **Document decisions:** Record why Policy B was chosen for audit purposes
3. **Plan for exceptions:** Have process for packages not in bundle
4. **Monitor disk usage:** Bundles accumulate over time
5. **Test thoroughly:** Validate on representative hosts before wide deployment

### For Compliance

1. **Save all bundles:** Archive for audit trail
2. **Document manifests:** Link to asset inventory
3. **Track package changes:** Pre/post diffs are your audit evidence
4. **Map to CVEs manually:** If required, maintain external CVE tracking
5. **Regular reviews:** Validate package selection quarterly
