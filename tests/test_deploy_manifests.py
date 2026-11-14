"""SLICE-100: multi-replica manifest and runbook contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "deploy" / "k8s" / "multi-replica.yaml"
SINGLE = ROOT / "deploy" / "k8s" / "deployment.yaml"
RUNBOOK = ROOT / "docs" / "guides" / "operations.md"


def _manifest() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def test_multi_replica_manifest_shapes():
    text = _manifest()
    assert text.count("kind: Deployment") == 4
    assert text.count("kind: Service") == 4
    for name in ("adk-console", "adk-mcp", "adk-audit", "adk-registry"):
        assert f"name: {name}" in text
    assert text.count("replicas: 3") == 2
    assert text.count("replicas: 2") == 2
    assert text.count("/healthz") == 8
    assert "kind: PodDisruptionBudget" in text


def test_multi_replica_manifest_has_no_local_state():
    text = _manifest()
    for forbidden in (
        "persistentVolumeClaim",
        "claimName",
        "StatefulSet",
        "SESSION_DB",
        "storageClassName",
    ):
        assert forbidden not in text


def test_multi_replica_manifest_uses_shared_backends():
    text = _manifest()
    for env in (
        "SESSION_URL",
        "REGISTRY_DATABASE_URL",
        "ARTIFACT_URL",
        "AUDIT_DATABASE_URL",
        "APPROVAL_DATABASE_URL",
        "GRANT_URL",
        "QUOTA_URL",
        "RATE_LIMIT_URL",
        "ADK_AUDIT_KEYRING",
        "ADK_MCP_AUTH_TOKEN",
    ):
        assert f"- name: {env}" in text
    assert text.count("secretKeyRef") >= 10
    assert "value: postgresql://" not in text
    assert "value: redis://" not in text


def test_operations_runbook_sections():
    text = RUNBOOK.read_text(encoding="utf-8")
    for heading in (
        "## 拓扑",
        "## 环境变量",
        "## 首次部署",
        "## 扩缩容",
        "## 备份与恢复",
        "## 密钥轮换",
        "## 时钟",
        "## 故障模式",
        "## 值守检查",
    ):
        assert heading in text


def test_single_replica_manifest_is_not_mistaken_for_multi():
    text = SINGLE.read_text(encoding="utf-8")
    assert "replicas: 1" in text
    assert "persistentVolumeClaim" in text
    assert "SESSION_DB" in text
