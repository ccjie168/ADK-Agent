<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface ToolEntry {
  tool_id: string;
  description?: string;
  source: string;
  data_classes: string[];
  requires_approval: boolean;
  tenant?: string | null;
  granted_agents: { id: string; version: string }[];
}

const auth = useAuthStore();
const tools = ref<ToolEntry[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("tools.read"));

function joinClasses(classes: string[]): string {
  return classes.join(", ") || "-";
}

function grantedLabel(granted: { id: string; version: string }[]): string {
  return granted.map((a) => `${a.id}@${a.version}`).join(", ") || "-";
}

onMounted(async () => {
  if (denied.value) return;
  try {
    tools.value = await getJson<ToolEntry[]>("/api/tools");
  } catch {
    error.value = "tools unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <PageHeader title="工具目录" description="工具目录与授权关系" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>工具 ID</th>
          <th>来源</th>
          <th>数据分级</th>
          <th>需审批</th>
          <th>授权 Agent</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="tool in tools" :key="tool.tool_id">
          <td>{{ tool.tool_id }}</td>
          <td>{{ tool.source }}</td>
          <td>{{ joinClasses(tool.data_classes) }}</td>
          <td>{{ tool.requires_approval ? "yes" : "no" }}</td>
          <td>{{ grantedLabel(tool.granted_agents) }}</td>
        </tr>
        <tr v-if="tools.length === 0">
          <td colspan="5" class="placeholder">暂无工具</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
