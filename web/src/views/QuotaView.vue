<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface QuotaUsage {
  window_runs: number;
  active_leases: number;
  max_runs: number | null;
  max_concurrent: number | null;
  window_seconds: number;
}

const auth = useAuthStore();
const quota = ref<QuotaUsage | null>(null);
const error = ref("");
const denied = computed(() => !auth.hasCapability("ops.read"));

function limitLabel(value: number | null): string {
  return value === null ? "无限" : String(value);
}

onMounted(async () => {
  if (denied.value) return;
  try {
    quota.value = await getJson<QuotaUsage>("/api/quota");
  } catch {
    error.value = "quota unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>配额</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <div v-else-if="quota" class="metric-grid">
      <div class="stat-card">
        <div class="stat-label">窗口运行数</div>
        <div class="stat-value">{{ quota.window_runs }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">活跃并发</div>
        <div class="stat-value">{{ quota.active_leases }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">运行上限</div>
        <div class="stat-value">{{ limitLabel(quota.max_runs) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">并发上限</div>
        <div class="stat-value">{{ limitLabel(quota.max_concurrent) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">窗口秒数</div>
        <div class="stat-value">{{ quota.window_seconds }}</div>
      </div>
    </div>
    <p v-else class="placeholder">暂无配额数据</p>
  </div>
</template>
