<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface CredentialBinding {
  credential_id: string;
  tenant: string;
  secret_ref: string;
  description?: string;
  enabled: boolean;
}

const auth = useAuthStore();
const credentials = ref<CredentialBinding[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("connectors.read"));

onMounted(async () => {
  if (denied.value) return;
  try {
    credentials.value = await getJson<CredentialBinding[]>("/api/credentials");
  } catch {
    error.value = "credentials unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>凭据</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>凭据 ID</th>
          <th>租户</th>
          <th>Secret 引用</th>
          <th>描述</th>
          <th>启用</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="binding in credentials" :key="binding.credential_id">
          <td>{{ binding.credential_id }}</td>
          <td>{{ binding.tenant }}</td>
          <td>{{ binding.secret_ref }}</td>
          <td>{{ binding.description ?? "" }}</td>
          <td>{{ binding.enabled ? "enabled" : "disabled" }}</td>
        </tr>
        <tr v-if="credentials.length === 0">
          <td colspan="5" class="placeholder">暂无凭据</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
