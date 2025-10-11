#!/bin/bash
set -euo pipefail

# Colors
R='\033[31m' G='\033[32m' Y='\033[33m' C='\033[36m' M='\033[35m' N='\033[0m'
log() { echo -e "${!1}$2${N}"; }

TEMP_DIR=$(mktemp -d)
trap "rm -rf ${TEMP_DIR}" EXIT

# If DRY_RUN=1, script will only generate Dockerfiles into the current directory
# and skip docker pull/build/push operations. Default is 0 (disabled).
DRY_RUN=${DRY_RUN:-0}

# Generate Dockerfile
gen_dockerfile() {
    local distro=$1 version=$2 base_img=$3 baseurl=$4 proxyurl=$5 pattern=$6
    local df
    if [[ "${DRY_RUN}" != "0" ]]; then
        df="./${distro}-${version}.Dockerfile"
    else
        df="${TEMP_DIR}/${distro}-${version}.Dockerfile"
    fi
    cat > "${df}" << EOF
FROM ${base_img}:${version}
LABEL maintainer="DawnMagnet"
RUN shopt -s nullglob && \
    sed -e 's|^mirrorlist=|#mirrorlist=|g' \
        -e 's|^#\? \?baseurl=${baseurl}|baseurl=${proxyurl}|g' \
        -i.bak ${pattern} && \
    (command -v dnf >/dev/null 2>&1 || (yum install -y dnf && hash -r)) && \
    dnf install -y \
        https://mirrors.ustc.edu.cn/rpmfusion/free/el/rpmfusion-free-release-${version}.noarch.rpm \
        https://mirrors.ustc.edu.cn/rpmfusion/nonfree/el/rpmfusion-nonfree-release-${version}.noarch.rpm && \
    if command -v crb >/dev/null 2>&1; then crb enable; fi && \
    sed -e 's|^metalink=|#metalink=|g' \
        -e 's|^#baseurl=http://download1.rpmfusion.org|baseurl=https://mirrors.ustc.edu.cn/rpmfusion|g' \
        -i.bak /etc/yum.repos.d/rpmfusion*.repo && \
    sed -e 's|^metalink=|#metalink=|g' \
        -e 's|^#baseurl=https\?://download.fedoraproject.org/pub/epel/|baseurl=https://mirrors.ustc.edu.cn/epel/|g' \
        -e 's|^#baseurl=https\?://download.example/pub/epel/|baseurl=https://mirrors.ustc.edu.cn/epel/|g' \
        -i.bak \
        /etc/yum.repos.d/epel{,-testing}.repo && \
    dnf clean all
EOF
    echo "${df}"
}

# Docker operations
docker_pull() {
    local img="$1:$2"
    log C "Pulling ${img}..."
    local old=$(docker image inspect --format='{{.Id}}' "${img}" 2>/dev/null || true)
    docker pull "${img}" >/dev/null 2>&1 || { log R "Pull failed: ${img}"; exit 1; }
    local new=$(docker image inspect --format='{{.Id}}' "${img}" 2>/dev/null)
    [[ "${old}" != "${new}" ]] && log G "Updated: ${old:0:12} -> ${new:0:12}" || log C "Up-to-date: ${new:0:12}"
}

docker_build() {
    local df=$1 img="$2:$3"
    log C "Building ${img}..."
    docker build -f "${df}" -t "${img}" ${TEMP_DIR} || { log R "Build failed: ${img}"; exit 1; }
    log G "Built ${img}"
}

docker_push() {
    local img="$1:$2"
    log C "Pushing ${img}..."
    docker push "${img}" || { log R "Push failed: ${img}"; exit 1; }
    log G "Pushed ${img}"
}

# Process images
process() {
    local name=$1 distro=$2 base=$3 baseurl=$4 proxyurl=$5 pattern=$6 tag=$7
    shift 7
    local versions=("$@")

    log Y "Processing ${name}..."
    for ver in "${versions[@]}"; do
        local df=$(gen_dockerfile "${distro}" "${ver}" "${base}" "${baseurl}" "${proxyurl}" "${pattern}")
        if [[ "${DRY_RUN}" != "0" ]]; then
            log C "[DRY_RUN] Generated Dockerfile: ${df}"
            continue
        fi
        docker_pull "${base}" "${ver}"
        docker_build "${df}" "${tag}" "${ver}"
        docker_push "${tag}" "${ver}"
    done
}

log M "Starting container image processing..."
log C "Temp: ${TEMP_DIR}"

process "Rocky Linux" "rocky" "rockylinux" \
    "http://dl.rockylinux.org/\$contentdir" \
    "https://mirrors.ustc.edu.cn/rocky" \
    "/etc/yum.repos.d/rocky*.repo /etc/yum.repos.d/Rocky*.repo" \
    "ghcr.io/dawnmagnet/rocky-cn" \
    8 9 10

process "Alma Linux" "alma" "almalinux" \
    "https://repo.almalinux.org" \
    "https://mirrors.aliyun.com" \
    "/etc/yum.repos.d/almalinux*.repo" \
    "ghcr.io/dawnmagnet/alma-cn" \
    8 9 10

process "CentOS Vault" "centos" "centos" \
    "http://mirror.centos.org/" \
    "https://mirrors.ustc.edu.cn/centos-vault/" \
    "/etc/yum.repos.d/CentOS-*.repo" \
    "ghcr.io/dawnmagnet/centos-cn" \
    7 8

# # Working In Progress(Because CentOS Stream 9/10 have different repo structure, without baseurl)
# process "CentOS Stream" "centos" "centos" \
#     "http://mirror.centos.org/" \
#     "https://mirrors.ustc.edu.cn/centos-vault/" \
#     "/etc/yum.repos.d/CentOS-*.repo" \
#     "ghcr.io/dawnmagnet/centos-cn" \
#     9 10

log M "All tasks completed!"

if [[ -n "${OVERRIDE_REGISTRY:-}" ]]; then
    log C "Images were pushed to override registry: ${OVERRIDE_REGISTRY}"
fi

cat > README-ghcr.md <<'EOF'
GitHub Actions CI
=================

This repository includes a GitHub Actions workflow at `.github/workflows/ci.yml` that builds container images and pushes them to GitHub Container Registry (GHCR) as `ghcr.io/<owner>/<image>:<tag>`.

What it does
- For each matrix entry (distro/version), it generates a Dockerfile variant, builds the image, and pushes to GHCR.

Authentication
- The workflow uses `GITHUB_TOKEN` by default which is available in Actions and has `packages: write` permission when the workflow `permissions` allow it. If you prefer, create a personal access token with `write:packages` scope and add it to repository secrets as `CR_PAT`, then replace `${{ secrets.GITHUB_TOKEN }}` in the workflow with `${{ secrets.CR_PAT }}`.

Repository settings
- Ensure the repository owner (user or org) allows GitHub Packages and the token used has permission to publish packages.

Notes
- The generated Dockerfile is a simplified reproduction of the logic inside `rhel-image-maintain.sh`. If you need more variants or customizations, extend the workflow matrix or port more of the script logic.

EOF

