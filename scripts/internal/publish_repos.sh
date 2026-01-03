#!/bin/bash
# Setup and verify HTTPS repository publishing
#
# This script configures httpd/nginx to serve repositories over HTTPS
#
# Usage:
#   ./publish_repos.sh --setup
#   ./publish_repos.sh --verify
#   ./publish_repos.sh --status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../common/logging.sh"
source "${SCRIPT_DIR}/../common/validation.sh"

REPO_BASE="/var/www/html/repos"
ACTION="${1:-status}"

usage() {
    cat <<EOF
Usage: $(basename "$0") [ACTION]

Manage HTTPS repository publishing.

Actions:
    --setup     Configure web server for repository publishing
    --verify    Verify repository accessibility
    --status    Show current repository status (default)
    --help      Show this help

EOF
    exit 0
}

case "$ACTION" in
    --setup)
        require_root
        log_script_start
        
        log_info "Setting up HTTPS repository publishing..."
        
        # Check for web server
        if command -v httpd &>/dev/null; then
            WEB_SERVER="httpd"
        elif command -v nginx &>/dev/null; then
            WEB_SERVER="nginx"
        else
            die "No web server found. Install httpd or nginx first."
        fi
        
        log_info "Detected web server: $WEB_SERVER"
        
        # Create repo directory
        validate_directory "$REPO_BASE" true
        
        if [[ "$WEB_SERVER" == "httpd" ]]; then
            # Create Apache configuration
            cat > /etc/httpd/conf.d/rpm-repos.conf <<'EOF'
# RPM Repository Configuration
# Managed by airgapped-rpm-repo-lite

<Directory "/var/www/html/repos">
    Options Indexes FollowSymLinks
    AllowOverride None
    Require all granted
    
    # Enable directory listing
    IndexOptions FancyIndexing NameWidth=*
    
    # Disable caching for repodata
    <FilesMatch "repomd\.xml$">
        Header set Cache-Control "no-cache, no-store, must-revalidate"
    </FilesMatch>
</Directory>

# Alias for clean URLs
Alias /repos /var/www/html/repos
EOF
            
            # Enable necessary modules
            log_info "Enabling Apache modules..."
            
            # Restart Apache
            systemctl enable httpd
            systemctl restart httpd
            log_success "Apache configured and restarted"
            
        else
            # Create Nginx configuration
            cat > /etc/nginx/conf.d/rpm-repos.conf <<'EOF'
# RPM Repository Configuration
# Managed by airgapped-rpm-repo-lite

server {
    listen 443 ssl;
    server_name _;
    
    ssl_certificate /etc/pki/tls/certs/localhost.crt;
    ssl_certificate_key /etc/pki/tls/private/localhost.key;
    
    location /repos {
        alias /var/www/html/repos;
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime on;
    }
}
EOF
            
            systemctl enable nginx
            systemctl restart nginx
            log_success "Nginx configured and restarted"
        fi
        
        # Set SELinux context
        if command -v semanage &>/dev/null; then
            log_info "Setting SELinux context..."
            semanage fcontext -a -t httpd_sys_content_t "${REPO_BASE}(/.*)?" 2>/dev/null || true
            restorecon -R "$REPO_BASE"
        fi
        
        # Open firewall
        if command -v firewall-cmd &>/dev/null; then
            log_info "Configuring firewall..."
            firewall-cmd --permanent --add-service=https 2>/dev/null || true
            firewall-cmd --reload 2>/dev/null || true
        fi
        
        log_success "HTTPS repository publishing configured"
        log_script_end 0
        ;;
        
    --verify)
        log_script_start
        log_info "Verifying repository accessibility..."
        
        HOSTNAME=$(hostname -f)
        ERRORS=0
        
        for os_version in rhel8 rhel9; do
            REPO_PATH="${REPO_BASE}/${os_version}/current"
            
            if [[ -L "$REPO_PATH" ]]; then
                log_info "Checking $os_version repository..."
                
                REPOMD_URL="https://${HOSTNAME}/repos/${os_version}/current/rpms/repodata/repomd.xml"
                
                if curl -sk --head "$REPOMD_URL" 2>/dev/null | grep -q "200"; then
                    log_success "  $os_version: ACCESSIBLE"
                else
                    log_error "  $os_version: NOT ACCESSIBLE"
                    ((ERRORS++))
                fi
            else
                log_warn "  $os_version: No current bundle"
            fi
        done
        
        if [[ $ERRORS -gt 0 ]]; then
            log_error "Verification failed with $ERRORS errors"
            exit 1
        fi
        
        log_success "All repositories are accessible"
        log_script_end 0
        ;;
        
    --status|status)
        log_info "Repository Status"
        log_info "================"
        log_info ""
        log_info "Base Path: $REPO_BASE"
        log_info "Hostname:  $(hostname -f)"
        log_info ""
        
        for os_version in rhel8 rhel9; do
            REPO_PATH="${REPO_BASE}/${os_version}"
            
            log_info "${os_version}:"
            
            if [[ -d "$REPO_PATH" ]]; then
                CURRENT="${REPO_PATH}/current"
                
                if [[ -L "$CURRENT" ]]; then
                    BUNDLE=$(readlink "$CURRENT")
                    RPM_COUNT=$(find "${CURRENT}/rpms" -name "*.rpm" 2>/dev/null | wc -l)
                    log_info "  Current Bundle: $BUNDLE"
                    log_info "  RPM Count:      $RPM_COUNT"
                    log_info "  URL: https://$(hostname -f)/repos/${os_version}/current/rpms"
                else
                    log_info "  Status: No current bundle"
                fi
                
                PREVIOUS="${REPO_PATH}/previous"
                if [[ -L "$PREVIOUS" ]]; then
                    log_info "  Previous: $(readlink "$PREVIOUS")"
                fi
            else
                log_info "  Status: Not initialized"
            fi
            
            log_info ""
        done
        ;;
        
    --help|-h)
        usage
        ;;
        
    *)
        die "Unknown action: $ACTION"
        ;;
esac
