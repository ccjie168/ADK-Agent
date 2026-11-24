<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface RunSummary {
  run_id: string;
  agent_id: string;
  status: string;
  started_at?: string | null;
  latency_ms?: number | null;
  cost_usd?: number | null;
  events: number;
}

const auth = useAuthStore();
const runs = ref<RunSummary[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("runs.read"));

function startedLabel(value: string | null | undefined): string {
  return String(value ?? "").replace("T", " ").slice(0, 19);
}

function latencyLabel(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `${value}ms`;
}

function costLabel(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : String(value);
}

onMounted(async () => {
  if (denied.value) return;
  try {
    runs.value = await getJson<RunSummary[]>("/api/runs?limit=50");
  } catch {
    error.value = "runs unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <PageHeader title="运行" description="运行记录与事件" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>运行 ID</th>
          <th>Agent</th>
          <th>状态</th>
          <th>开始时间</th>
          <th>延迟</th>
          <th>成本</th>
          <th>事件</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="run in runs" :key="run.run_id">
          <td>{{ String(run.run_id).slice(0, 12) }}</td>
          <td>{{ run.agent_id }}</td>
          <td>{{ run.status }}</td>
          <td>{{ startedLabel(run.started_at) }}</td>
          <td>{{ latencyLabel(run.latency_ms) }}</td>
          <td>{{ costLabel(run.cost_usd) }}</td>
          <td>{{ run.events }}</td>
        </tr>
        <tr v-if="runs.length === 0">
          <td colspan="7" class="placeholder">暂无运行</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
