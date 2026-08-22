#!/usr/bin/env python3
"""
Generate deploy/chals/docker-compose.generated.yml from every challenge.yml.

    deploy/chals/generate.py            # write the prod file
    deploy/chals/generate.py --check    # fail if the prod file is stale (CI uses this)
    deploy/chals/generate.py --dev      # write the local-dev file (build:, no TLS)

The generated compose is the single source of truth for what runs on the
challenge host. Nobody hand-edits it; you change a challenge.yml and re-run.

Flags are NOT written here. They come from deploy/chals/flags.env, which is
sops/age-encrypted in the repo and decrypted on the host at deploy time.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("generate: PyYAML is required -> pip install pyyaml")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from domains import derive as _derive  # noqa: E402

_D = _derive()
REGISTRY = "ghcr.io/nocohackers"
TAG = "2026"

# Production and local-dev differ in three ways and only three: where the image
# comes from (pull vs build), what domain the routers match, and whether TLS is
# on. Everything else - hardening, ports, networks - is identical, on purpose:
# dev should fail the same way prod would.
PROD = {
    "out": ROOT / "deploy" / "chals" / "docker-compose.generated.yml",
    "domain": _D["NOCO_CHALLENGE_BASE"],
    "build": False,
    "tls": True,
    "edge_net": "noco-edge",
}
DEV = {
    "out": ROOT / "deploy" / "dev" / "docker-compose.dev.yml",
    # *.localhost resolves to 127.0.0.1 in every browser and in most host
    # resolvers (systemd-resolved does it by default). `make dev-hosts` prints
    # /etc/hosts lines for anything that doesn't.
    "domain": "chal.localhost",
    "build": True,
    "tls": False,
    "edge_net": "noco-dev-edge",
}

HEADER = """\
# GENERATED FILE - DO NOT EDIT.
# Produced by deploy/chals/generate.py from the challenges/ tree.
# Run `make -C deploy/chals generate` after changing any challenge.yml.
"""


def service_name(chal_dir: Path) -> str:
    return f"{chal_dir.parent.name}-{chal_dir.name}"


# Writable paths each base image needs on an otherwise read-only rootfs.
TMPFS = {
    "web": ["/tmp:size=64m", "/var/run", "/var/cache/nginx",
            "/srv/www:size=64m,uid=101,gid=101,mode=0755"],
    "tcp": ["/tmp:size=64m", "/flag:size=1m"],
}


def hardening(x: dict) -> dict:
    """Defaults applied to every challenge container.

    These are the difference between "a player got RCE in one challenge" and
    "a player got the whole challenge host". Authors can raise the resource
    caps in challenge.yml; they cannot opt out of the security options.
    """
    return {
        "restart": "unless-stopped",
        "read_only": True,
        "tmpfs": TMPFS.get(x.get("kind", "web"), TMPFS["web"]),
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "pids_limit": x.get("pids", 128),
        "mem_limit": x.get("memory", "256m"),
        "cpus": float(x.get("cpus", 0.5)),
        "logging": {"driver": "json-file",
                    "options": {"max-size": "10m", "max-file": "3"}},
    }


def build_service(chal_dir: Path, data: dict, cfg: dict) -> tuple[str, dict] | None:
    x = data.get("x-noco") or {}
    kind = x.get("kind")
    if kind == "static":
        return None

    name = service_name(chal_dir)
    svc: dict = {"container_name": name}

    if cfg["build"]:
        # Local dev builds from source so you can iterate without CI/registry.
        rel = chal_dir.relative_to(ROOT).as_posix()
        svc["build"] = {"context": "../..", "dockerfile": f"{rel}/Dockerfile"}
    else:
        svc["image"] = f"{REGISTRY}/chal-{name}:{TAG}"

    svc["environment"] = {"FLAG": "${FLAG_%s:?missing flag}" % name.upper().replace("-", "_")}
    svc.update(hardening(x))

    if kind == "web":
        sub = x["subdomain"]
        router = {
            "traefik.enable": "true",
            f"traefik.http.routers.{name}.rule": f"Host(`{sub}.{cfg['domain']}`)",
            f"traefik.http.services.{name}.loadbalancer.server.port": "8080",
        }
        if cfg["tls"]:
            router[f"traefik.http.routers.{name}.entrypoints"] = "websecure"
            router[f"traefik.http.routers.{name}.tls.certresolver"] = "le"
        else:
            router[f"traefik.http.routers.{name}.entrypoints"] = "web"
        svc["networks"] = ["edge"]
        svc["labels"] = router
    elif kind == "tcp":
        # Raw sockets can't be SNI-routed, so they get a real published port.
        # See INFRASTRUCTURE.md, "Why TCP challenges don't get subdomains".
        svc["ports"] = [f"{x['port']}:1337"]
        svc["networks"] = ["isolated"]
        # socat drops from root to the unprivileged `ctf` user per connection,
        # which needs these two caps back after cap_drop: ALL. Nothing else.
        svc["cap_add"] = ["SETUID", "SETGID", "SETPCAP"]

    return name, svc


def generate(cfg: dict) -> str:
    services: dict[str, dict] = {}
    for manifest in sorted((ROOT / "challenges").rglob("challenge.yml")):
        if manifest.parent.name == "TEMPLATE":
            continue
        data = yaml.safe_load(manifest.read_text())
        built = build_service(manifest.parent, data, cfg)
        if built:
            services[built[0]] = built[1]

    doc = {
        "services": services,
        "networks": {
            # Traefik lives on `edge` and talks to web challenges.
            "edge": {"external": True, "name": cfg["edge_net"]},
            # tcp challenges get no shared network at all: they cannot reach
            # each other, and they cannot reach the web challenges.
            "isolated": {"driver": "bridge", "internal": False},
        },
    }
    banner = HEADER if not cfg["build"] else HEADER.replace(
        "deploy/chals/generate.py", "deploy/chals/generate.py --dev")
    return banner + yaml.safe_dump(doc, sort_keys=False, width=100)


def write_dev_dynamic(cfg: dict) -> Path:
    """Emit a Traefik file-provider route table for local dev.

    The dev Traefik uses the file provider, not the Docker provider: some
    daemons refuse the Docker SDK's default API version, and the file provider
    depends on none of that. Traefik reaches each container by name on the
    shared network.
    """
    routers, services = {}, {}
    for manifest in sorted((ROOT / "challenges").rglob("challenge.yml")):
        if manifest.parent.name == "TEMPLATE":
            continue
        data = yaml.safe_load(manifest.read_text())
        x = data.get("x-noco") or {}
        if x.get("kind") != "web":
            continue
        name = service_name(manifest.parent)
        routers[name] = {"rule": f"Host(`{x['subdomain']}.{cfg['domain']}`)",
                         "entrypoints": ["web"], "service": name}
        services[name] = {"loadBalancer": {"servers": [{"url": f"http://{name}:8080"}]}}

    # The scoreboard rides the same proxy.
    routers["ctfd"] = {"rule": "Host(`ctf.localhost`)", "entrypoints": ["web"],
                       "service": "ctfd"}
    services["ctfd"] = {"loadBalancer": {"servers": [{"url": "http://noco-dev-ctfd:8000"}]}}

    doc = {"http": {"routers": routers, "services": services}}
    out = ROOT / "deploy" / "dev" / "traefik-dynamic.yml"
    out.write_text("# GENERATED by generate.py --dev. Traefik file-provider routes.\n"
                   + yaml.safe_dump(doc, sort_keys=False, width=100))
    return out


def main() -> int:
    cfg = DEV if "--dev" in sys.argv else PROD
    rendered = generate(cfg)
    out = cfg["out"]
    if "--check" in sys.argv:
        current = out.read_text() if out.is_file() else ""
        if current != rendered:
            print(f"generate: {out.name} is stale.")
            print("          run: make -C deploy/chals generate" +
                  (" (and: deploy/chals/generate.py --dev)" if cfg is DEV else ""))
            return 1
        print("generate: up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered)
    n = rendered.count("container_name:")
    print(f"generate: wrote {out.relative_to(ROOT)} ({n} challenge services)")
    if cfg is DEV:
        dyn = write_dev_dynamic(cfg)
        print(f"generate: wrote {dyn.relative_to(ROOT)} (traefik routes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
