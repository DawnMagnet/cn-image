generate_cn_dockerfile

Minimal generator to produce Dockerfiles that rewrite distro repos to CN mirrors.

Usage

- Generate a Dockerfile for Rocky Linux 8 and write to ./rockylinux-8.Dockerfile:

  go run main.go rockylinux:8

- Print to stdout:

  go run main.go almalinux:9 --stdout

- Override mirror base URL:

  go run main.go centos:7 --mirror https://mirrors.aliyun.com

- Generate for UBI 9:

  go run main.go ubi:9.4

Notes

- Script is written in Go and uses `go run` for execution.
- Supported distros: rockylinux, almalinux, centos, ubi
- Automatically handles CRB (EL9+) and PowerTools (EL8).
- Disables remote sensing/subscription-manager for UBI images.
