package main

import (
	"flag"
	"fmt"
	"os"
	"regexp"
	"sort"
	"strings"
)

type DistroConfig struct {
	Base            string
	BaseURL         string
	ProxyURL        string
	Pattern         string
	EnableCRB       bool
	EnableRPMFusion bool
	EnableEPEL      bool
	DockerPath      string
}

var DistroRegistry = map[string]DistroConfig{
	"rockylinux": {
		Base:            "rockylinux",
		BaseURL:         "http://dl.rockylinux.org/$contentdir",
		ProxyURL:        "https://mirrors.ustc.edu.cn/rocky",
		Pattern:         "/etc/yum.repos.d/rocky*.repo /etc/yum.repos.d/Rocky*.repo",
		EnableCRB:       true,
		EnableRPMFusion: true,
		EnableEPEL:      true,
		DockerPath:      "quay.io/rockylinux/rockylinux",
	},
	"almalinux": {
		Base:            "almalinux",
		BaseURL:         "https://repo.almalinux.org",
		ProxyURL:        "https://mirrors.aliyun.com",
		Pattern:         "/etc/yum.repos.d/almalinux*.repo",
		EnableCRB:       true,
		EnableRPMFusion: true,
		EnableEPEL:      true,
	},
	"centos": {
		Base:            "centos",
		BaseURL:         "http://mirror.centos.org/",
		ProxyURL:        "https://mirrors.ustc.edu.cn/centos-vault/",
		Pattern:         "/etc/yum.repos.d/CentOS-*.repo",
		EnableCRB:       false,
		EnableRPMFusion: true,
		EnableEPEL:      true,
	},
	"ubi": {
		Base:            "ubi",
		BaseURL:         "https://cdn-ubi.redhat.com/content/public/ubi",
		ProxyURL:        "https://mirrors.aliyun.com/rockylinux", // UBI often uses Rocky/Alma mirrors for extra packages
		Pattern:         "/etc/yum.repos.d/ubi.repo",
		EnableCRB:       true,
		EnableRPMFusion: true,
		EnableEPEL:      true,
		DockerPath:      "registry.access.redhat.com/ubi8/ubi", // Default to ubi8, will be adjusted
	},
}

func extractMajorVersion(version string) string {
	re := regexp.MustCompile(`^(\d+)`)
	match := re.FindStringSubmatch(version)
	if len(match) > 1 {
		return match[1]
	}
	return version
}

func parseImageReference(image string) (string, string, error) {
	parts := strings.Split(image, ":")
	if len(parts) != 2 {
		return "", "", fmt.Errorf("image must be in the form '<distro>:<version>'")
	}
	return strings.ToLower(strings.TrimSpace(parts[0])), strings.TrimSpace(parts[1]), nil
}

func buildRunCommand(cfg DistroConfig, distro, version, proxyURL string) string {
	majorVersion := extractMajorVersion(version)

	var commands []string
	commands = append(commands, "shopt -s nullglob")

	// UBI specific: disable subscription-manager and remote sensing
	if distro == "ubi" {
		commands = append(commands,
			"sed -i 's/enabled=1/enabled=0/g' /etc/yum/pluginconf.d/subscription-manager.conf",
			"rm -f /etc/yum.repos.d/ubi.repo",
		)
		// For UBI, we actually want to add Rocky or Alma repos because UBI itself is limited
		// We'll use Rocky as the base for "extra" repos on UBI
		repoContent := fmt.Sprintf(`[baseos]
name=Rocky Linux %s - BaseOS
baseurl=https://mirrors.ustc.edu.cn/rocky/%s/BaseOS/$basearch/os/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-rockyofficial

[appstream]
name=Rocky Linux %s - AppStream
baseurl=https://mirrors.ustc.edu.cn/rocky/%s/AppStream/$basearch/os/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-rockyofficial`, majorVersion, version, majorVersion, version)

		commands = append(commands, fmt.Sprintf("echo -e '%s' > /etc/yum.repos.d/rocky-mirror.repo", strings.ReplaceAll(repoContent, "\n", "\\n")))
	} else {
		sedBase := fmt.Sprintf("sed -e 's|^mirrorlist=|#mirrorlist=|g' -e 's|^#\\? \\?baseurl=%s|baseurl=%s|g' -i.bak %s",
			cfg.BaseURL, proxyURL, cfg.Pattern)
		commands = append(commands, sedBase)
	}

	commands = append(commands, "(command -v dnf >/dev/null 2>&1 || (yum install -y dnf && hash -r))")

	if cfg.EnableRPMFusion {
		rpmfusionFree := fmt.Sprintf("https://mirrors.ustc.edu.cn/rpmfusion/free/el/rpmfusion-free-release-%s.noarch.rpm", majorVersion)
		rpmfusionNonFree := fmt.Sprintf("https://mirrors.ustc.edu.cn/rpmfusion/nonfree/el/rpmfusion-nonfree-release-%s.noarch.rpm", majorVersion)
		commands = append(commands, fmt.Sprintf("dnf install -y %s %s", rpmfusionFree, rpmfusionNonFree))
	}

	if cfg.EnableCRB {
		if majorVersion == "8" {
			commands = append(commands, "dnf install -y 'dnf-command(config-manager)' && dnf config-manager --set-enabled powertools || true")
		} else {
			commands = append(commands, "if command -v crb >/dev/null 2>&1; then crb enable; fi")
		}
	}

	if cfg.EnableRPMFusion {
		rpmfusionMirror := "https://mirrors.ustc.edu.cn/rpmfusion"
		commands = append(commands, fmt.Sprintf("sed -e 's|^metalink=|#metalink=|g' -e 's|^#baseurl=http://download1.rpmfusion.org|baseurl=%s|g' -i.bak /etc/yum.repos.d/rpmfusion*.repo", rpmfusionMirror))
	}

	if cfg.EnableEPEL {
		epelMirror := "https://mirrors.ustc.edu.cn/epel/"
		commands = append(commands, fmt.Sprintf("sed -e 's|^metalink=|#metalink=|g' -e 's|^#baseurl=https\\?://download.fedoraproject.org/pub/epel/|baseurl=%s|g' -e 's|^#baseurl=https\\?://download.example/pub/epel/|baseurl=%s|g' -i.bak /etc/yum.repos.d/epel{,-testing}.repo", epelMirror, epelMirror))
	}

	commands = append(commands, "dnf clean all")

	return "RUN " + strings.Join(commands, " && \\\n    ")
}

func renderDockerfile(distro, version, mirrorOverride string) (string, error) {
	cfg, ok := DistroRegistry[distro]
	if !ok {
		var supported []string
		for k := range DistroRegistry {
			supported = append(supported, k)
		}
		sort.Strings(supported)
		return "", fmt.Errorf("unsupported distro '%s'. Supported: %s", distro, strings.Join(supported, ", "))
	}

	proxyURL := mirrorOverride
	if proxyURL == "" {
		proxyURL = cfg.ProxyURL
	}

	runLine := buildRunCommand(cfg, distro, version, proxyURL)

	baseImage := ""
	if distro == "ubi" {
		majorVersion := extractMajorVersion(version)
		baseImage = fmt.Sprintf("registry.access.redhat.com/ubi%s/ubi:%s", majorVersion, version)
	} else if cfg.DockerPath != "" {
		baseImage = fmt.Sprintf("%s:%s", cfg.DockerPath, version)
	} else {
		baseImage = fmt.Sprintf("%s:%s", cfg.Base, version)
	}

	return fmt.Sprintf("FROM %s\nLABEL maintainer=\"DawnMagnet\"\n%s\n", baseImage, runLine), nil
}

func main() {
	outFlag := flag.String("out", "", "Output Dockerfile path")
	mirrorFlag := flag.String("mirror", "", "Optional mirror base URL")
	stdoutFlag := flag.Bool("stdout", false, "Print to stdout instead of writing a file")

	flag.Parse()

	if flag.NArg() < 1 {
		fmt.Fprintln(os.Stderr, "Usage: cn-image [options] <distro>:<version>")
		os.Exit(1)
	}

	image := flag.Arg(0)
	distro, version, err := parseImageReference(image)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(2)
	}

	dockerfile, err := renderDockerfile(distro, version, *mirrorFlag)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(3)
	}

	if *stdoutFlag {
		fmt.Print(dockerfile)
		return
	}

	outputPath := *outFlag
	if outputPath == "" {
		outputPath = fmt.Sprintf("./%s-%s.Dockerfile", distro, version)
	}

	err = os.WriteFile(outputPath, []byte(dockerfile), 0644)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error writing %s: %v\n", outputPath, err)
		os.Exit(4)
	}

	fmt.Println(outputPath)
}
