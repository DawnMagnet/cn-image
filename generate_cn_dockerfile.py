#!/usr/bin/env python3
"""Minimal CLI that generates a Dockerfile redirected to CN mirrors for a given base image tag.

Usage examples:
    ./generate_cn_dockerfile.py rockylinux:8
    ./generate_cn_dockerfile.py almalinux:9 --out ./alma-9.Dockerfile
    ./generate_cn_dockerfile.py centos:7 --stdout

Only uses Python standard library so it can run inside GitHub Actions runners.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

DISTROS = {
    "rockylinux": {
        "base": "rockylinux",
        "baseurl": "http://dl.rockylinux.org/$contentdir",
        "proxyurl": "https://mirrors.ustc.edu.cn/rocky",
        "pattern": "/etc/yum.repos.d/rocky*.repo /etc/yum.repos.d/Rocky*.repo",
    },
    "almalinux": {
        "base": "almalinux",
        "baseurl": "https://repo.almalinux.org",
        "proxyurl": "https://mirrors.aliyun.com",
        "pattern": "/etc/yum.repos.d/almalinux*.repo",
    },
    "centos": {
        "base": "centos",
        "baseurl": "http://mirror.centos.org/",
        "proxyurl": "https://mirrors.ustc.edu.cn/centos-vault/",
        "pattern": "/etc/yum.repos.d/CentOS-*.repo",
    },
}


DOCKERFILE_TMPL = textwrap.dedent(r"""
    FROM {base}:{version}
    LABEL maintainer="generated-by-generate_cn_dockerfile.py"
    RUN shopt -s nullglob && \\\n+        sed -e 's|^mirrorlist=|#mirrorlist=|g' \\
            -e 's|^#\? \?baseurl={baseurl}|baseurl={proxyurl}|g' \\
            -i.bak {pattern} && \\
        (command -v dnf >/dev/null 2>&1 || (yum install -y dnf && hash -r)) && \\
        dnf clean all || true
    """)


def parse_image(img: str) -> tuple[str, str]:
    """Parse an image string like 'rockylinux:8' into (distro, version).

    Raises SystemExit on invalid format.
    """
    if ":" not in img:
        print("Error: image must be in the form '<distro>:<version>'", file=sys.stderr)
        raise SystemExit(2)
    # split on last colon to allow names with repo prefixes if any
    distro, version = img.rsplit(":", 1)
    distro = distro.strip().lower()
    version = version.strip()
    if not distro or not version:
        print("Error: invalid image name", file=sys.stderr)
        raise SystemExit(2)
    return distro, version


def generate(distro: str, version: str, mirror_override: str | None = None) -> str:
    cfg = DISTROS.get(distro)
    if cfg is None:
        print(
            f"Error: unsupported distro '{distro}'. Supported: {', '.join(DISTROS)}",
            file=sys.stderr,
        )
        raise SystemExit(3)

    baseurl = cfg["baseurl"]
    proxyurl = mirror_override or cfg["proxyurl"]
    pattern = cfg["pattern"]

    return DOCKERFILE_TMPL.format(
        base=cfg["base"],
        version=version,
        baseurl=baseurl,
        proxyurl=proxyurl,
        pattern=pattern,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate a CN-mirror Dockerfile for the given base image tag"
    )
    p.add_argument("image", help="Base image and tag, e.g. rockylinux:8 or almalinux:9")
    p.add_argument(
        "--out",
        help="Output Dockerfile path (default: ./<distro>-<version>.Dockerfile)",
    )
    p.add_argument(
        "--mirror", help="Optional mirror base URL to use instead of the built-in one"
    )
    p.add_argument(
        "--stdout",
        action="store_true",
        help="Print to stdout instead of writing a file",
    )
    args = p.parse_args(argv)

    distro, version = parse_image(args.image)
    dockerfile = generate(distro, version, mirror_override=args.mirror)

    default_out = f"./{distro}-{version}.Dockerfile"
    out_path = args.out or default_out

    if args.stdout:
        print(dockerfile)
        return 0

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(dockerfile)
    except OSError as e:
        print(f"Error writing {out_path}: {e}", file=sys.stderr)
        return 4

    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
