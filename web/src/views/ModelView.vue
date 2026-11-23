<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface ModelSummary {
  recent_calls: number;
  aliases: string[];
  fallbacks: number;
}

const auth = useAuthStore();
const summary = ref<ModelSummary | null>(null);
const error = ref("");
const denied = computed(() => !auth.hasCapability("model.read"));

function aliasesLabel(aliases: string[] | undefined): string {
  return aliases && aliases.length ? aliases.join(", ") : "—";
}

onMounted(async () => {
  if (denied.value) return;
  try {
    summary.value = await getJson<ModelSummary>("/api/model");
  } catch {
    error.value = "model unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>模型</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <div v-else-if="summary" class="metric-grid">
      <div class="stat-card">
        <div class="stat-label">最近调用</div>
        <div class="stat-value">{{ summary.recent_calls }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">使用别名</div>
        <div class="stat-value">{{ aliasesLabel(summary.aliases) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">降级次数</div>
        <div class="stat-value">{{ summary.fallbacks }}</div>
      </div>
    </div>
    <p v-else class="placeholder">暂无模型数据</p>
  </div>
</template>
