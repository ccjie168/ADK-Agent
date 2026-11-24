<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface RagSummary {
  recent_retrievals: number;
  last_top_k: number | null;
  last_returned: number | null;
}

const auth = useAuthStore();
const rag = ref<RagSummary | null>(null);
const error = ref("");
const denied = computed(() => !auth.hasCapability("ops.read"));

function nullableLabel(value: number | null): string {
  return value === null ? "—" : String(value);
}

onMounted(async () => {
  if (denied.value) return;
  try {
    rag.value = await getJson<RagSummary>("/api/rag");
  } catch {
    error.value = "rag unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <PageHeader title="检索" description="检索调用与过滤" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <div v-else-if="rag" class="metric-grid">
      <div class="stat-card">
        <div class="stat-label">最近检索</div>
        <div class="stat-value">{{ rag.recent_retrievals }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">最近 top_k</div>
        <div class="stat-value">{{ nullableLabel(rag.last_top_k) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">最近返回</div>
        <div class="stat-value">{{ nullableLabel(rag.last_returned) }}</div>
      </div>
    </div>
    <p v-else class="placeholder">暂无检索数据</p>
  </div>
</template>
