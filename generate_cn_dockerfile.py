#!/usr/bin/env python3
"""Generate a Dockerfile that rewrites yum/dnf repos to CN mirrors.

The script intentionally depends only on the Python standard library so it can be
used in minimal environments (e.g. CI jobs, GitHub Actions, container builds).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DistroConfig:
    """Container image metadata and mirror rewrites for a distro."""

    base: str
    baseurl: str
    proxyurl: str
    pattern: str
    enable_crb: bool = True
    enable_rpmfusion: bool = True
    enable_epel: bool = True
    # Optional docker image path prefix (registry/repo), without tag
    docker_path: str | None = None


DISTRO_REGISTRY: Mapping[str, DistroConfig] = {
    "rockylinux": DistroConfig(
        base="rockylinux",
        baseurl="http://dl.rockylinux.org/$contentdir",
        proxyurl="https://mirrors.ustc.edu.cn/rocky",
        pattern="/etc/yum.repos.d/rocky*.repo /etc/yum.repos.d/Rocky*.repo",
        docker_path="quay.io/rockylinux/rockylinux",
    ),
    "almalinux": DistroConfig(
        base="almalinux",
        baseurl="https://repo.almalinux.org",
        proxyurl="https://mirrors.aliyun.com",
        pattern="/etc/yum.repos.d/almalinux*.repo",
        # docker_path="quay.io/almalinux/almalinux",
    ),
    "centos": DistroConfig(
        base="centos",
        baseurl="http://mirror.centos.org/",
        proxyurl="https://mirrors.ustc.edu.cn/centos-vault/",
        pattern="/etc/yum.repos.d/CentOS-*.repo",
        enable_crb=False,
        # docker_path="quay.io/centos/centos",
    ),
}


def parse_image_reference(image: str) -> tuple[str, str]:
    """Split *image* into (distro, version) and validate the format."""
    if ":" not in image:
        print("Error: image must be in the form '<distro>:<version>'", file=sys.stderr)
        raise SystemExit(2)

    distro, version = image.rsplit(":", 1)
    distro = distro.strip().lower()
    version = version.strip()

    if not distro or not version:
        print("Error: invalid image name", file=sys.stderr)
        raise SystemExit(2)

    return distro, version


def render_dockerfile(distro: str, version: str, mirror_override: str | None) -> str:
    """Return the Dockerfile content for *distro* and *version*."""
    cfg = DISTRO_REGISTRY.get(distro)
    if cfg is None:
        supported = ", ".join(sorted(DISTRO_REGISTRY))
        print(
            f"Error: unsupported distro '{distro}'. Supported: {supported}",
            file=sys.stderr,
        )
        raise SystemExit(3)

    proxyurl = mirror_override or cfg.proxyurl
    run_line = build_run_command(cfg, version, proxyurl)
    # Use custom docker_path if provided, else fall back to base name
    if cfg.docker_path:
        base_image = f"{cfg.docker_path}:{version}"
    else:
        base_image = f"{cfg.base}:{version}"

    return f'FROM {base_image}\nLABEL maintainer="DawnMagnet"\n{run_line}\n'


def extract_major_version(version: str) -> str:
    """Return the leading numeric component of *version* for URL templating."""
    candidate = version
    for sep in (".", "-", "_"):
        if sep in version:
            candidate = version.split(sep, 1)[0]
            break

    digits = "".join(ch for ch in candidate if ch.isdigit())
    return digits or candidate


def build_run_command(cfg: DistroConfig, version: str, proxyurl: str) -> str:
    """Construct the RUN instruction matching the reference Dockerfile format."""
    major_version = extract_major_version(version)

    sed_base = (
        "sed -e 's|^mirrorlist=|#mirrorlist=|g'         "
        f"-e 's|^#\\? \\?baseurl={cfg.baseurl}|baseurl={proxyurl}|g'         "
        f"-i.bak {cfg.pattern}"
    )

    commands = [
        "shopt -s nullglob",
        sed_base,
        "(command -v dnf >/dev/null 2>&1 || (yum install -y dnf && hash -r))",
    ]

    if cfg.enable_rpmfusion:
        rpmfusion_free = (
            "https://mirrors.ustc.edu.cn/rpmfusion/free/el/"
            f"rpmfusion-free-release-{major_version}.noarch.rpm"
        )
        rpmfusion_nonfree = (
            "https://mirrors.ustc.edu.cn/rpmfusion/nonfree/el/"
            f"rpmfusion-nonfree-release-{major_version}.noarch.rpm"
        )
        commands.append(
            f"dnf install -y         {rpmfusion_free}         {rpmfusion_nonfree}"
        )

    if cfg.enable_crb:
        commands.append("if command -v crb >/dev/null 2>&1; then crb enable; fi")

    if cfg.enable_rpmfusion:
        rpmfusion_mirror = "https://mirrors.ustc.edu.cn/rpmfusion"
        commands.append(
            "sed -e 's|^metalink=|#metalink=|g'         "
            f"-e 's|^#baseurl=http://download1.rpmfusion.org|baseurl={rpmfusion_mirror}|g'         "
            "-i.bak /etc/yum.repos.d/rpmfusion*.repo"
        )

    if cfg.enable_epel:
        epel_mirror = "https://mirrors.ustc.edu.cn/epel/"
        commands.append(
            "sed -e 's|^metalink=|#metalink=|g'         "
            f"-e 's|^#baseurl=https\\?://download.fedoraproject.org/pub/epel/|baseurl={epel_mirror}|g'         "
            f"-e 's|^#baseurl=https\\?://download.example/pub/epel/|baseurl={epel_mirror}|g'         "
            "-i.bak         /etc/yum.repos.d/epel{,-testing}.repo"
        )

    commands.append("dnf clean all")

    return "RUN " + " &&     ".join(commands)


def write_output(content: str, path: Path) -> None:
    """Write *content* to *path*, reporting any filesystem issues."""
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        print(f"Error writing {path}: {exc}", file=sys.stderr)
        raise SystemExit(4)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser used by :func:`main`."""
    parser = argparse.ArgumentParser(
        description="Generate a CN-mirror Dockerfile for the given base image tag",
    )
    parser.add_argument(
        "image",
        help="Base image and tag, e.g. rockylinux:8 or almalinux:9",
    )
    parser.add_argument(
        "--out",
        help="Output Dockerfile path (default: ./<distro>-<version>.Dockerfile)",
    )
    parser.add_argument(
        "--mirror",
        help="Optional mirror base URL to use instead of the built-in one",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print to stdout instead of writing a file",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    distro, version = parse_image_reference(args.image)
    dockerfile = render_dockerfile(distro, version, mirror_override=args.mirror)

    if args.stdout:
        print(dockerfile)
        return 0

    output_path = Path(args.out or f"./{distro}-{version}.Dockerfile")
    write_output(dockerfile, output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
