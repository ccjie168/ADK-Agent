"""SLICE-148: the AD/OIDC guide ships configurable, schema-valid examples."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from adk_agent.identity import OidcBrowserConfig, OidcConfig

GUIDE = Path(__file__).resolve().parent.parent / "docs" / "guides" / "ad-oidc.md"


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def _json_blocks() -> list[str]:
    return re.findall(r"```json\n(.*?)```", _guide(), re.DOTALL)


def test_guide_covers_the_required_sections():
    text = _guide()

    for heading in (
        "# 企业内网的身份认证",
        "## 先决条件",
        "## 配置格式",
        "## Entra ID（Azure AD）",
        "## ADFS",
        "## 控制台浏览器登录（可选）",
        "## 启动服务",
        "## 排障",
        "## 不支持的方式",
    ):
        assert heading in text


def test_every_json_example_validates():
    blocks = _json_blocks()

    kinds = {"config": 0, "browser": 0}
    for block in blocks:
        data = json.loads(block)
        if "issuer" in data:
            OidcConfig.model_validate(data)
            kinds["config"] += 1
        elif "authorization_endpoint" in data:
            OidcBrowserConfig.model_validate(data)
            kinds["browser"] += 1
        else:
            pytest.fail(f"unrecognised example: {sorted(data)}")

    assert kinds["config"] >= 2
    assert kinds["browser"] == 1


def test_guide_examples_require_the_issuer_and_audience():
    example = json.loads(_json_blocks()[0])

    for field in ("issuer", "audience"):
        broken = dict(example)
        broken.pop(field)
        with pytest.raises(ValidationError):
            OidcConfig.model_validate(broken)


def test_guide_names_the_limits_and_decisions():
    text = _guide()

    assert "--oidc-config" in text
    assert "ADR-0007" in text
    assert "docs/contracts/credentials.md" in text
    assert "Kerberos" in text
    assert "client_secret_env" in text


def _section(name: str) -> str:
    for part in re.split(r"^## ", _guide(), flags=re.MULTILINE):
        if part.startswith(name):
            return part
    raise AssertionError(f"section not found: {name}")


def test_each_provider_has_its_own_valid_example():
    entra = json.loads(
        re.search(r"```json\n(.*?)```", _section("Entra ID（Azure AD）"), re.DOTALL).group(1)
    )
    adfs = json.loads(re.search(r"```json\n(.*?)```", _section("ADFS"), re.DOTALL).group(1))

    assert OidcConfig.model_validate(entra).tenant_claim == "tid"
    assert OidcConfig.model_validate(adfs).audience == "https://adk-agent.example.com"


def test_browser_example_requests_an_api_scope():
    block = re.search(r"```json\n(.*?)```", _section("控制台浏览器登录（可选）"), re.DOTALL).group(
        1
    )
    browser = OidcBrowserConfig.model_validate(json.loads(block))

    assert any(scope.startswith("api://") for scope in browser.scopes)


def test_cited_contract_exists():
    assert (GUIDE.parent.parent / "contracts" / "credentials.md").is_file()
