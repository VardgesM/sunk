"""Disposable independent gateway for opt-in Docker integration tests."""

import ipaddress
import json
import os
import subprocess
from pathlib import Path


class Gateway:
    def __init__(self, root: Path, work: Path, project: str, env: dict[str, str]):
        self.project, self.env = project + "-gateway", env
        self.network = project + "-web"
        self.volumes = [project + "-certs", project + "-caddy-config"]
        self.image = project + ":gateway"
        override = work / "gateway-image.json"
        override.write_text(json.dumps({"services": {"caddy": {"image": self.image}}}))
        self.prefix = [
            "docker",
            "compose",
            "-p",
            self.project,
            "--project-directory",
            str(root / "deploy/gateway"),
            "-f",
            str(root / "deploy/gateway/docker-compose.yml"),
            "-f",
            str(override),
        ]

    def run(self, args: list[str], *, check=True) -> str:
        result = subprocess.run(
            args,
            env=dict(os.environ, **self.env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        if check and result.returncode:
            raise RuntimeError("Isolated gateway operation failed: " + result.stderr[-3000:])
        return result.stdout.strip()

    def compose(self, *args: str) -> str:
        return self.run([*self.prefix, *args])

    def prepare(self, http_port: int, https_port: int) -> None:
        self.run(
            [
                "docker",
                "network",
                "create",
                "--label",
                f"gateway-smoke={self.project}",
                self.network,
            ]
        )
        network = json.loads(self.run(["docker", "network", "inspect", self.network]))[0]
        subnet = ipaddress.ip_network(network["IPAM"]["Config"][0]["Subnet"])
        self.env.update(
            GATEWAY_NETWORK=self.network,
            GATEWAY_IPV4=str(subnet.network_address + 2),
            GATEWAY_BIND_ADDRESS="127.0.0.1",
            GATEWAY_HTTP_PORT=str(http_port),
            GATEWAY_HTTPS_PORT=str(https_port),
            MODBUS_HOST="localhost",
            MODBUS_SCHEME="http",
            CADDY_DATA_VOLUME=self.volumes[0],
            CADDY_CONFIG_VOLUME=self.volumes[1],
            MODBUS_API_UPSTREAM="modbus-api:8000",
            MODBUS_FRONTEND_UPSTREAM="modbus-frontend:8080",
        )
        for volume in self.volumes:
            self.run(
                ["docker", "volume", "create", "--label", f"gateway-smoke={self.project}", volume]
            )
        self.compose("build")
        self.compose(
            "run",
            "--rm",
            "--no-deps",
            "caddy",
            "caddy",
            "validate",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
        # Reserve the static proxy IP before dynamically addressed application containers start.
        self.compose("up", "-d", "--no-build", "--wait")

    def identity(self) -> tuple[str, str]:
        identifier = self.compose("ps", "-q", "caddy")
        details = json.loads(self.run(["docker", "inspect", identifier]))[0]
        return identifier, details["State"]["StartedAt"]

    def cleanup(self) -> None:
        self.run([*self.prefix, "down", "--remove-orphans"], check=False)
        for volume in self.volumes:
            result = self.run(["docker", "volume", "inspect", volume], check=False)
            if (
                result
                and json.loads(result)[0].get("Labels", {}).get("gateway-smoke") == self.project
            ):
                self.run(["docker", "volume", "rm", volume], check=False)
        result = self.run(["docker", "network", "inspect", self.network], check=False)
        if result and json.loads(result)[0].get("Labels", {}).get("gateway-smoke") == self.project:
            self.run(["docker", "network", "rm", self.network], check=False)
        self.run(["docker", "image", "rm", self.image], check=False)
