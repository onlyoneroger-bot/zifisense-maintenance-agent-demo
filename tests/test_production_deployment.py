from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_production_compose_exposes_only_caddy_and_hardens_application():
    compose = yaml.safe_load((ROOT / "compose.production.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    app = services["maintenance-agent"]
    caddy = services["caddy"]

    assert "ports" not in app
    assert app["expose"] == ["8080"]
    assert app["read_only"] is True
    assert app["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in app["security_opt"]
    assert app["environment"]["RATE_LIMIT_MCP_PER_MINUTE"].endswith("6000}")
    assert "MCP_DOMAIN" in app["environment"]["MCP_ALLOWED_HOSTS"]
    assert sorted(caddy["ports"]) == ["443:443", "443:443/udp", "80:80"]
    assert caddy["depends_on"]["maintenance-agent"]["condition"] == "service_healthy"


def test_caddy_and_production_env_preserve_streaming_and_fail_closed():
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.production.example").read_text(encoding="utf-8")

    assert "flush_interval -1" in caddyfile
    assert "response_header_timeout 25s" in caddyfile
    assert "reverse_proxy maintenance-agent:8080" in caddyfile
    assert "REPLACE_WITH_64_HEX_SHA256" in env_example
    assert "RATE_LIMIT_MCP_PER_MINUTE=6000" in env_example
    assert "LLM_MAX_RETRIES=0" in env_example
    assert "LLM_TIMEOUT_SECONDS=12" in env_example
    assert "Bearer " not in env_example


def test_deployment_probe_scripts_are_runnable():
    for script in ("mcp_sdk_smoke.py", "mcp_load_probe.py"):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "--url" in result.stdout
