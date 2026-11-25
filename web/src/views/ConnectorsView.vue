<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface ConnectorSpec {
  connector_id: string;
  tenant?: string | null;
  kind: string;
  base_url: string;
  methods: string[];
  enabled: boolean;
}

const KINDS = ["http", "openapi", "mcp"];
const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"];

const auth = useAuthStore();
const connectors = ref<ConnectorSpec[]>([]);
const draft = ref({
  connector_id: "",
  tenant: "",
  kind: "http",
  base_url: "",
  path_prefixes: "/",
  auth_ref: "",
  timeout_seconds: 10,
});
const draftMethods = ref<string[]>(["GET"]);
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("connectors.read"));
const canManage = computed(() => auth.hasCapability("connectors.manage"));

function tenantLabel(connector: ConnectorSpec): string {
  return connector.tenant ?? "global";
}

function methodsLabel(connector: ConnectorSpec): string {
  return connector.methods.join(", ");
}

function toggleMethod(method: string) {
  const index = draftMethods.value.indexOf(method);
  if (index >= 0) draftMethods.value.splice(index, 1);
  else draftMethods.value.push(method);
}

async function reload() {
  try {
    connectors.value = await getJson<ConnectorSpec[]>("/api/connectors");
  } catch {
    error.value = "connectors unavailable";
  }
}

async function register() {
  const prefixes = draft.value.path_prefixes
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  const body: Record<string, unknown> = {
    connector_id: draft.value.connector_id.trim(),
    kind: draft.value.kind,
    base_url: draft.value.base_url.trim(),
    methods: draftMethods.value,
    path_prefixes: prefixes.length ? prefixes : ["/"],
    timeout_seconds: Number(draft.value.timeout_seconds),
  };
  if (draft.value.tenant.trim()) body.tenant = draft.value.tenant.trim();
  if (draft.value.auth_ref.trim()) body.auth_ref = draft.value.auth_ref.trim();
  let response: Response;
  try {
    response = await apiFetch("/api/connectors", {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch {
    message.value = "注册失败: 网络错误";
    return;
  }
  if (response.ok) {
    message.value = `已注册 ${String(body.connector_id)}`;
    await reload();
    return;
  }
  const codes: Record<string, string> = {
    invalid_connector: "连接器定义无效",
    connector_conflict: "同名连接器已存在且定义不同",
    credential_unbound: "引用的凭据未绑定或已禁用",
  };
  const code = await errorCode(response);
  message.value = `注册失败: ${codes[code] ?? response.status}`;
}

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? "";
  } catch {
    return "";
  }
}

async function disable(connector: ConnectorSpec) {
  let response: Response;
  try {
    response = await apiFetch(`/api/connectors/${encodeURIComponent(connector.connector_id)}/disable`, {
      method: "POST",
    });
  } catch {
    message.value = "禁用失败: 网络错误";
    return;
  }
  message.value = response.ok
    ? `已禁用 ${connector.connector_id}`
    : `禁用失败: ${response.status}`;
  await reload();
}

onMounted(async () => {
  if (denied.value) return;
  await reload();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="连接器" description="出站连接器与凭据引用" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <div class="table-wrap">
  <table class="data-table">
        <thead>
          <tr>
            <th>连接器 ID</th>
            <th>租户</th>
            <th>类型</th>
            <th>Base URL</th>
            <th>方法</th>
            <th>启用</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="connector in connectors" :key="connector.connector_id">
            <td>{{ connector.connector_id }}</td>
            <td>{{ tenantLabel(connector) }}</td>
            <td>{{ connector.kind }}</td>
            <td>{{ connector.base_url }}</td>
            <td>{{ methodsLabel(connector) }}</td>
            <td>{{ connector.enabled ? "yes" : "no" }}</td>
            <td>
              <button
                v-if="canManage && connector.enabled"
                class="link"
                @click="disable(connector)"
              >
                禁用
              </button>
            </td>
          </tr>
          <tr v-if="connectors.length === 0">
            <td colspan="7" class="placeholder">暂无连接器</td>
          </tr>
        </tbody>
        </table>
      </div>

      <template v-if="canManage">
        <h2>注册连接器</h2>
        <div class="row">
          <input v-model="draft.connector_id" class="grow" placeholder="连接器 ID" />
          <input v-model="draft.tenant" class="grow" placeholder="租户（留空为全局）" />
          <select v-model="draft.kind">
            <option v-for="kind in KINDS" :key="kind" :value="kind">{{ kind }}</option>
          </select>
        </div>
        <div class="row">
          <input v-model="draft.base_url" class="grow" placeholder="https://api.example.com" />
          <input v-model="draft.path_prefixes" class="grow" placeholder="路径前缀，逗号分隔" />
        </div>
        <div class="row">
          <input v-model="draft.auth_ref" class="grow" placeholder="secret://tenant/name（可选）" />
          <input
            v-model.number="draft.timeout_seconds"
            class="grow"
            type="number"
            min="1"
            max="60"
            placeholder="超时秒"
          />
        </div>
        <div class="capability-grid">
          <label v-for="method in METHODS" :key="method">
            <input
              type="checkbox"
              :checked="draftMethods.includes(method)"
              @change="toggleMethod(method)"
            />
            <span>{{ method }}</span>
          </label>
        </div>
        <div class="row">
          <button class="primary" @click="register">注册</button>
        </div>
      </template>
    </template>
  </div>
</template>
