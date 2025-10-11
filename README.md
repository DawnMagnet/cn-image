generate_cn_dockerfile

Minimal generator to produce Dockerfiles that rewrite distro repos to CN mirrors.

Usage

- Generate a Dockerfile for Rocky Linux 8 and write to ./rockylinux-8.Dockerfile:

  ./generate_cn_dockerfile.py rockylinux:8

- Print to stdout:

  ./generate_cn_dockerfile.py almalinux:9 --stdout

- Override mirror base URL:

  ./generate_cn_dockerfile.py centos:7 --mirror https://mirrors.aliyun.com

Notes

- Script only depends on Python standard library so it's safe to run inside CI (GitHub Actions).
- Supported distros: rockylinux, almalinux, centos
