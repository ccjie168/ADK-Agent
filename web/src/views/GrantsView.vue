<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";
import EmptyState from "../components/EmptyState.vue";

interface GrantRecord {
  request_id: string;
  tool_id: string;
  agent_id: string;
  version: string;
  status: string;
  expires_at: string | null;
}

const auth = useAuthStore();
const grants = ref<GrantRecord[]>([]);
const reason = ref("");
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("grants.read"));
const canDecide = computed(() => auth.hasCapability("grants.decide"));

function expiring(grant: GrantRecord): boolean {
  if (grant.status !== "approved" || !grant.expires_at) return false;
  const left = Date.parse(grant.expires_at) - Date.now();
  return left > 0 && left <= 24 * 3600 * 1000;
}

function expiresLabel(grant: GrantRecord): string {
  return String(grant.expires_at ?? "").replace("T", " ").slice(0, 19);
}

async function reload() {
  try {
    grants.value = await getJson<GrantRecord[]>("/api/tool-grants");
  } catch {
    error.value = "授权存储不可用：配置 --tool-grants-dir 或 GRANT_URL 后刷新";
  }
}

async function decide(grant: GrantRecord, approved: boolean) {
  let response: Response;
  try {
    response = await apiFetch(
      `/api/tool-grants/${encodeURIComponent(grant.request_id)}/decide`,
      { method: "POST", body: JSON.stringify({ approved, reason: reason.value }) },
    );
  } catch {
    message.value = "决定失败: 网络错误";
    return;
  }
  if (response.ok) {
    message.value = approved ? "已批准" : "已拒绝";
    reason.value = "";
    await reload();
    return;
  }
  const codes: Record<string, string> = {
    grant_not_found: "授权请求不存在",
    grant_already_decided: "该请求已决定",
    grant_expired: "请求已过期",
    grant_store_unavailable: "授权存储不可用",
  };
  message.value = `决定失败: ${codes[await errorCode(response)] ?? response.status}`;
}

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? "";
  } catch {
    return "";
  }
}

onMounted(async () => {
  if (denied.value) return;
  await reload();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="工具授权" description="工具临时授权与到期" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
    <p v-if="message" class="login-msg">{{ message }}</p>
    <div v-if="canDecide" class="row">
      <input v-model="reason" class="grow" placeholder="决定理由（可选）" autocomplete="off" />
    </div>
    <div v-if="grants.length > 0" class="table-wrap">
  <table class="data-table">
      <thead>
        <tr>
          <th>工具 ID</th>
          <th>Agent</th>
          <th>版本</th>
          <th>状态</th>
          <th>到期时间</th>
          <th v-if="canDecide" />
        </tr>
      </thead>
      <tbody>
        <tr v-for="grant in grants" :key="grant.request_id">
          <td>{{ grant.tool_id }}</td>
          <td>{{ grant.agent_id }}</td>
          <td>{{ grant.version }}</td>
          <td>
            {{ grant.status }}
            <span v-if="expiring(grant)" class="badge muted">expiring</span>
          </td>
          <td>{{ expiresLabel(grant) }}</td>
          <td v-if="canDecide" class="row">
            <button
              v-if="grant.status === 'pending'"
              class="link"
              @click="decide(grant, true)"
            >
              批准
            </button>
            <button
              v-if="grant.status === 'pending'"
              class="link"
              @click="decide(grant, false)"
            >
              拒绝
            </button>
          </td>
        </tr>
              </tbody>
      </table>
    </div>
    <EmptyState v-else description="工具授权请求来自运行时需要临时放行的工具调用；由 admin 在下方批准或拒绝。">暂无授权请求</EmptyState>
    </template>
  </div>
</template>
