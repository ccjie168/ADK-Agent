<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface ConnectorSpec {
  connector_id: string;
  tenant?: string | null;
  kind: string;
  base_url: string;
  methods: string[];
  enabled: boolean;
}

const auth = useAuthStore();
const connectors = ref<ConnectorSpec[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("connectors.read"));

function tenantLabel(connector: ConnectorSpec): string {
  return connector.tenant ?? "global";
}

function methodsLabel(connector: ConnectorSpec): string {
  return connector.methods.join(", ");
}

onMounted(async () => {
  if (denied.value) return;
  try {
    connectors.value = await getJson<ConnectorSpec[]>("/api/connectors");
  } catch {
    error.value = "connectors unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>连接器</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>连接器 ID</th>
          <th>租户</th>
          <th>类型</th>
          <th>Base URL</th>
          <th>方法</th>
          <th>启用</th>
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
        </tr>
        <tr v-if="connectors.length === 0">
          <td colspan="6" class="placeholder">暂无连接器</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
