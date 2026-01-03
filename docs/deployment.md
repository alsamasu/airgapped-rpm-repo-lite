# Deployment Guide

This guide covers the architecture, server roles, and prerequisites for deploying
the airgapped-rpm-repo-lite system.

## Architecture Overview

The system consists of four distinct server roles:

```
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL NETWORK (Connected)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐              ┌─────────────────┐           │
│  │    ext-rhel8    │              │    ext-rhel9    │           │
│  │   (Builder)     │              │    (Builder)    │           │
│  │                 │              │                 │           │
│  │ - RHEL 8.10     │              │ - RHEL 9.6      │           │
│  │ - RH CDN access │              │ - RH CDN access │           │
│  │ - Subscription  │              │ - Subscription  │           │
│  └─────────────────┘              └─────────────────┘           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                           ║ AIR GAP ║
┌─────────────────────────────────────────────────────────────────┐
│                   INTERNAL NETWORK (Air-gapped)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐              ┌─────────────────┐           │
│  │    int-rhel8    │              │    int-rhel9    │           │
│  │   (Repo Server) │              │  (Repo Server)  │           │
│  │                 │              │                 │           │
│  │ - RHEL 8.x      │              │ - RHEL 9.x      │           │
│  │ - HTTPS server  │              │ - HTTPS server  │           │
│  │ - No internet   │              │ - No internet   │           │
│  └────────┬────────┘              └────────┬────────┘           │
│           │                                │                    │
│           └────────────┬───────────────────┘                    │
│                        │                                        │
│           ┌────────────┴───────────────┐                        │
│           │      INTERNAL HOSTS        │                        │
│           │  rhel8-host-01, 02, ...    │                        │
│           │  rhel9-host-01, 02, ...    │                        │
│           └────────────────────────────┘                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Server Roles

### External Builders (ext-rhel8, ext-rhel9)

**Purpose:** Build RPM bundles by downloading updates from Red Hat CDN.

**Requirements:**
- RHEL 8.10 (for ext-rhel8) or RHEL 9.6 (for ext-rhel9)
- Valid Red Hat subscription with CDN access
- Internet connectivity
- Minimum 100GB disk space for downloads
- Python 3.9+
- createrepo_c package
- zstd package (recommended)

**Installation:**

```bash
# Register with Red Hat
subscription-manager register --username=USER --password=PASS

# Attach subscription
subscription-manager attach --auto

# Enable required repos
subscription-manager repos --enable=rhel-8-for-x86_64-baseos-rpms
subscription-manager repos --enable=rhel-8-for-x86_64-appstream-rpms

# Install dependencies
dnf install -y python3 createrepo_c zstd git

# Clone repository
git clone https://github.com/your-org/airgapped-rpm-repo-lite.git /opt/airgapped-rpm-repo-lite

# Create working directories
mkdir -p /var/lib/rpm-bundles /var/lib/rpm-manifests
```

### Internal Servers (int-rhel8, int-rhel9)

**Purpose:** Serve RPM repositories to internal hosts over HTTPS.

**Requirements:**
- RHEL 8.x (for int-rhel8) or RHEL 9.x (for int-rhel9)
- No internet connectivity (air-gapped)
- HTTPS-capable web server (httpd or nginx)
- TLS certificate (self-signed or internal CA)
- Minimum 200GB disk space for repository storage

**Installation:**

```bash
# Install dependencies (from local media or initial bundle)
dnf install -y httpd mod_ssl createrepo_c

# Clone repository (transferred via media)
cp -r /media/airgapped-rpm-repo-lite /opt/

# Create repository directories
mkdir -p /var/www/html/repos/rhel8
mkdir -p /var/www/html/repos/rhel9

# Configure HTTPS
/opt/airgapped-rpm-repo-lite/scripts/internal/publish_repos.sh --setup

# Start web server
systemctl enable --now httpd
```

### Internal Hosts (rhel8-host-*, rhel9-host-*)

**Purpose:** Target systems to be patched.

**Requirements:**
- RHEL 8.x or 9.x
- Network access to internal repo server
- SSH access for Ansible
- CA certificate for internal repos (if using self-signed)

## Network Requirements

### External Network
- Outbound HTTPS (443) to Red Hat CDN (cdn.redhat.com)
- Outbound HTTPS (443) to subscription.rhsm.redhat.com

### Internal Network
- HTTPS (443) from hosts to internal repo servers
- SSH (22) from Ansible control node to all hosts

## TLS Configuration

### Using Self-Signed Certificates

Generate on internal server:

```bash
# Generate CA key and certificate
openssl genrsa -out /etc/pki/CA/private/internal-ca.key 4096
openssl req -x509 -new -nodes \
    -key /etc/pki/CA/private/internal-ca.key \
    -sha256 -days 3650 \
    -out /etc/pki/CA/certs/internal-ca.crt \
    -subj "/CN=Internal CA/O=Organization"

# Generate server certificate
openssl genrsa -out /etc/pki/tls/private/int-rhel8.key 2048
openssl req -new \
    -key /etc/pki/tls/private/int-rhel8.key \
    -out /tmp/int-rhel8.csr \
    -subj "/CN=int-rhel8.internal/O=Organization"

# Sign with CA
openssl x509 -req \
    -in /tmp/int-rhel8.csr \
    -CA /etc/pki/CA/certs/internal-ca.crt \
    -CAkey /etc/pki/CA/private/internal-ca.key \
    -CAcreateserial \
    -out /etc/pki/tls/certs/int-rhel8.crt \
    -days 365 -sha256
```

### Distributing CA Certificate

The CA certificate must be installed on all internal hosts:

```bash
# Copy to trust anchors
cp internal-ca.crt /etc/pki/ca-trust/source/anchors/

# Update trust store
update-ca-trust extract
```

## Initial Deployment Steps

### Step 1: Deploy External Builders

1. Install RHEL 8.10 on ext-rhel8
2. Install RHEL 9.6 on ext-rhel9
3. Register with Red Hat subscription
4. Install airgapped-rpm-repo-lite

### Step 2: Deploy Internal Servers

1. Install RHEL on int-rhel8 and int-rhel9
2. Configure HTTPS with TLS certificates
3. Install airgapped-rpm-repo-lite (via media transfer)
4. Configure web server for repository hosting

### Step 3: Configure Internal Hosts

1. Install CA certificate on each host
2. Configure repository file pointing to internal server
3. Verify connectivity to internal repo

### Step 4: Initial Manifest Collection

1. Run manifest collection playbook
2. Transfer manifests to external builders
3. Build initial bundles

### Step 5: Initial Bundle Import

1. Transfer bundles across air gap
2. Import bundles on internal servers
3. Verify repository accessibility

## Directory Structure

### External Builders

```
/opt/airgapped-rpm-repo-lite/    # Application code
/var/lib/rpm-bundles/            # Built bundles
/var/lib/rpm-manifests/          # Collected manifests
/tmp/bundle-build-*/             # Temporary build directory
```

### Internal Servers

```
/opt/airgapped-rpm-repo-lite/    # Application code
/var/www/html/repos/             # Repository root
├── rhel8/
│   ├── current -> bundle-rhel8-20240115T120000Z
│   ├── previous -> bundle-rhel8-20240101T120000Z
│   └── bundle-rhel8-20240115T120000Z/
│       ├── rpms/
│       │   └── repodata/
│       ├── manifests/
│       ├── metadata.json
│       └── SHA256SUMS
└── rhel9/
    ├── current -> bundle-rhel9-20240115T120000Z
    └── bundle-rhel9-20240115T120000Z/
        └── ...
```

## Security Considerations

1. **Bundle Integrity:** Always verify SHA256 checksums before importing
2. **TLS:** Use proper TLS certificates for HTTPS
3. **Access Control:** Restrict SSH access to authorized personnel
4. **Audit Logging:** Enable audit logging on all servers
5. **Media Handling:** Use secure procedures for physical media transfer

## Troubleshooting

### Common Issues

**Subscription not found on external builder:**
```bash
subscription-manager refresh
subscription-manager list --available
```

**Repository not accessible from internal host:**
```bash
# Check certificate
curl -v https://int-rhel8.internal/repos/rhel8/current/rpms/repodata/repomd.xml

# Verify CA trust
openssl s_client -connect int-rhel8.internal:443 -CApath /etc/pki/tls/certs/
```

**DNF errors during patching:**
```bash
# Clean cache
dnf clean all

# Check repo configuration
cat /etc/yum.repos.d/internal-rhel8.repo

# Test repository
dnf repolist -v
```

## Python Dependencies

The Python scripts require dependencies to be installed on external builders and internal servers.

### Install on RHEL Servers

Use the provided provisioning script:

```bash
# Run as root
/opt/airgapped-rpm-repo-lite/scripts/provision/install_python_deps.sh
```

This installs:
- jsonschema (manifest validation)
- requests (HTTP operations)
- dnf-plugins-core (dependency resolution)

### Air-gapped Internal Servers

For internal servers without internet:

1. Download wheels on external builder:
```bash
pip download -d /tmp/wheels jsonschema requests
```

2. Transfer wheels via media

3. Install offline:
```bash
pip install --no-index --find-links=/tmp/wheels jsonschema requests
```

## vSphere Lab Environment (Testing)

For E2E testing in vSphere environments:

### Required VMs

| VM Name | OS Version | Role | Network |
|---------|------------|------|---------|
| ext-rhel8 | RHEL 8.10 | External builder | Connected |
| ext-rhel9 | RHEL 9.6 | External builder | Connected |
| int-rhel8 | RHEL 8.x | Internal repo server | Air-gapped |
| int-rhel9 | RHEL 9.x | Internal repo server | Air-gapped |
| rhel8-tester | RHEL 8.10 | Test target | Air-gapped |
| rhel9-tester | RHEL 9.6 | Test target | Air-gapped |

### VM Specifications

| Role | vCPU | RAM | Disk |
|------|------|-----|------|
| External Builder | 2 | 4GB | 100GB |
| Internal Server | 2 | 4GB | 200GB |
| Tester | 1 | 2GB | 40GB |

### Network Configuration

- **External Network:** VLAN with internet access, DHCP or static
- **Internal Network:** Isolated VLAN, no internet routing
- **Air-gap Simulation:** No routes between external and internal VLANs

### VMware Tools

VMware Tools must be installed on all VMs for:
- IP address reporting
- Graceful shutdown
- Guest operations

```bash
# Install open-vm-tools
dnf install -y open-vm-tools
systemctl enable --now vmtoolsd
```
