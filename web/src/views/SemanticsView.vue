<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";
import EmptyState from "../components/EmptyState.vue";

interface ConceptScheme {
  scheme_id: string;
  concepts: unknown[];
}

const auth = useAuthStore();
const schemes = ref<ConceptScheme[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("ops.read"));

function schemeLabel(scheme: ConceptScheme): string {
  return `${scheme.scheme_id} (${scheme.concepts.length} 概念)`;
}

onMounted(async () => {
  if (denied.value) return;
  try {
    schemes.value = await getJson<ConceptScheme[]>("/api/semantics");
  } catch {
    error.value = "术语表存储不可用：配置语义层存储后刷新";
  }
});
</script>

<template>
  <div class="panel">
    <PageHeader title="语义层" description="术语表与概念" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <div v-else class="metric-grid">
      <div v-for="scheme in schemes" :key="scheme.scheme_id" class="stat-card">
        <div class="stat-label">术语表</div>
        <div class="stat-value">{{ schemeLabel(scheme) }}</div>
      </div>
      <EmptyState
        v-if="schemes.length === 0"
        description="术语表用于检索与语义层；导入术语表后在此查看。"
      >暂无术语表</EmptyState>
    </div>
  </div>
</template>
