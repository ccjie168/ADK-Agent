<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface AuditSigning {
  active: string | null;
  kids: string[];
  legacy: boolean;
  error?: string;
}

interface CredentialKeys {
  active_key_id: string | null;
  by_key_id: Record<string, number>;
  needs_rewrap: number;
  error?: string;
}

interface AuditBlock {
  backend: string;
  records: number | null;
  last_event_at: string | null;
  verified: boolean | null;
  checked_records?: number;
  error?: string;
}

interface ScanBlock {
  generated_at: string;
  codeql: { open?: number };
  dependencies: { vulnerabilities?: number };
}

interface SecuritySummary {
  audit: AuditBlock;
  keys: { audit_signing: AuditSigning; credentials: CredentialKeys };
  policy: { version: string | null; bindings: number | null };
  scans: ScanBlock | null;
}

const BACKENDS: Record<string, string> = {
  file: "文件",
  http: "审计服务",
  db: "Postgres",
  memory: "内存",
  none: "未配置",
  unknown: "未知",
};

const AUDIT_ERRORS: Record<string, string> = {
  audit_unavailable: "审计后端不可用",
  backend_unsupported: "当前审计后端不支持链校验",
  verify_timeout: "校验超时（10 秒），请稍后重试",
  chain_broken: "审计链断裂",
  verify_failed: "校验失败",
  invalid_keyring: "审计签名密钥配置无效",
};

const CREDENTIAL_ERRORS: Record<string, string> = {
  credential_store_unavailable: "凭据存储不可用",
};

const auth = useAuthStore();
const summary = ref<SecuritySummary | null>(null);
const loading = ref(false);
const verifying = ref(false);
const loadError = ref("");
const denied = computed(() => !auth.hasCapability("ops.read"));

function label(code: string | undefined, table: Record<string, string>): string {
  if (!code) return "";
  return table[code] ?? "未知错误";
}

async function load(verify = false) {
  if (denied.value) return;
  if (verify) verifying.value = true;
  else loading.value = true;
  try {
    const path = verify ? "/api/security?verify=1" : "/api/security";
    summary.value = await getJson<SecuritySummary>(path);
    loadError.value = "";
  } catch {
    loadError.value = "无法加载安全摘要";
  } finally {
    loading.value = false;
    verifying.value = false;
  }
}

function verifiedLabel(value: boolean | null): string {
  if (value === true) return "已通过";
  if (value === false) return "未通过";
  return "未校验";
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="panel">
    <h1>安全</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="loading" class="placeholder">加载中…</p>
    <p v-else-if="loadError" class="placeholder">{{ loadError }}</p>
    <div v-else-if="summary" class="card-grid security-grid">
      <section class="security-card">
        <h2>审计</h2>
        <dl>
          <dt>后端</dt>
          <dd>{{ BACKENDS[summary.audit.backend] ?? "未知" }}</dd>
          <dt>记录数</dt>
          <dd>{{ summary.audit.records === null ? "不可用" : summary.audit.records }}</dd>
          <dt>最近事件</dt>
          <dd>{{ summary.audit.last_event_at ?? "无记录" }}</dd>
          <dt>链校验</dt>
          <dd>{{ verifiedLabel(summary.audit.verified) }}</dd>
          <template v-if="summary.audit.checked_records !== undefined">
            <dt>校验条数</dt>
            <dd>{{ summary.audit.checked_records }}</dd>
          </template>
        </dl>
        <p v-if="summary.audit.error" class="security-error">
          {{ label(summary.audit.error, AUDIT_ERRORS) }}
        </p>
        <button class="primary" :disabled="verifying" @click="load(true)">
          {{ verifying ? "校验中…" : "校验审计链" }}
        </button>
      </section>

      <section class="security-card">
        <h2>密钥</h2>
        <dl>
          <dt>审计签名</dt>
          <dd>{{ summary.keys.audit_signing.active ?? "未配置" }}</dd>
          <dt>保留 key</dt>
          <dd>{{ summary.keys.audit_signing.kids.join(", ") || "无" }}</dd>
          <dt>旧记录密钥</dt>
          <dd>{{ summary.keys.audit_signing.legacy ? "已保留" : "无" }}</dd>
          <dt>凭据 KEK</dt>
          <dd>{{ summary.keys.credentials.active_key_id ?? "未配置" }}</dd>
          <dt>待重包裹</dt>
          <dd>{{ summary.keys.credentials.needs_rewrap }}</dd>
        </dl>
        <p v-if="summary.keys.audit_signing.error" class="security-error">
          {{ label(summary.keys.audit_signing.error, AUDIT_ERRORS) }}
        </p>
        <p v-if="summary.keys.credentials.error" class="security-error">
          {{ label(summary.keys.credentials.error, CREDENTIAL_ERRORS) }}
        </p>
        <ul class="security-keys">
          <li v-for="(count, key) in summary.keys.credentials.by_key_id" :key="key">
            {{ key }}：{{ count }}
          </li>
        </ul>
      </section>

      <section class="security-card">
        <h2>策略</h2>
        <dl>
          <dt>版本</dt>
          <dd>{{ summary.policy.version ?? "未配置" }}</dd>
          <dt>绑定数</dt>
          <dd>{{ summary.policy.bindings ?? "—" }}</dd>
        </dl>
      </section>

      <section class="security-card">
        <h2>扫描</h2>
        <p v-if="!summary.scans" class="placeholder">未提供扫描报告</p>
        <dl v-else>
          <dt>生成时间</dt>
          <dd>{{ summary.scans.generated_at }}</dd>
          <dt>CodeQL 未关闭</dt>
          <dd>{{ summary.scans.codeql.open ?? "—" }}</dd>
          <dt>依赖漏洞</dt>
          <dd>{{ summary.scans.dependencies.vulnerabilities ?? "—" }}</dd>
        </dl>
      </section>
    </div>
  </div>
</template>
