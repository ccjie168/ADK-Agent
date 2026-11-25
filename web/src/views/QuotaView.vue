<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";
import EmptyState from "../components/EmptyState.vue";

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
    error.value = "配额数据不可用：配置 --quota-config 后刷新";
  }
});
</script>

<template>
  <div class="panel">
    <PageHeader title="配额" description="配额用量与限制" />
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
    <EmptyState v-else description="配额从 --quota-config 读取；未配置时所有租户不受限。">暂无配额数据</EmptyState>
  </div>
</template>
