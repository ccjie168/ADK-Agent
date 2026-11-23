<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

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
const error = ref("");
const denied = computed(() => !auth.hasCapability("grants.read"));

function expiring(grant: GrantRecord): boolean {
  if (grant.status !== "approved" || !grant.expires_at) return false;
  const left = Date.parse(grant.expires_at) - Date.now();
  return left > 0 && left <= 24 * 3600 * 1000;
}

function expiresLabel(grant: GrantRecord): string {
  return String(grant.expires_at ?? "").replace("T", " ").slice(0, 19);
}

onMounted(async () => {
  if (denied.value) return;
  try {
    grants.value = await getJson<GrantRecord[]>("/api/tool-grants");
  } catch {
    error.value = "tool grants unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>工具授权</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>工具 ID</th>
          <th>Agent</th>
          <th>版本</th>
          <th>状态</th>
          <th>到期时间</th>
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
        </tr>
        <tr v-if="grants.length === 0">
          <td colspan="5" class="placeholder">暂无授权请求</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
