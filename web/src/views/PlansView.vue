<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface PlanSummary {
  plan_id: string;
  tenant: string;
  status: string;
  steps: number;
  approvals: number;
  started_at?: string | null;
}

const auth = useAuthStore();
const plans = ref<PlanSummary[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("runs.read"));

function startedLabel(value: string | null | undefined): string {
  return String(value ?? "").replace("T", " ").slice(0, 19);
}

onMounted(async () => {
  if (denied.value) return;
  try {
    plans.value = await getJson<PlanSummary[]>("/api/plans?limit=50");
  } catch {
    error.value = "plans unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>计划</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>计划 ID</th>
          <th>租户</th>
          <th>状态</th>
          <th>步骤</th>
          <th>审批</th>
          <th>开始时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="plan in plans" :key="plan.plan_id">
          <td>{{ plan.plan_id }}</td>
          <td>{{ plan.tenant }}</td>
          <td>{{ plan.status }}</td>
          <td>{{ plan.steps }}</td>
          <td>{{ plan.approvals }}</td>
          <td>{{ startedLabel(plan.started_at) }}</td>
        </tr>
        <tr v-if="plans.length === 0">
          <td colspan="6" class="placeholder">暂无计划</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
