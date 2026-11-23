<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

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
    error.value = "semantics unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>语义层</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <div v-else class="metric-grid">
      <div v-for="scheme in schemes" :key="scheme.scheme_id" class="stat-card">
        <div class="stat-label">术语表</div>
        <div class="stat-value">{{ schemeLabel(scheme) }}</div>
      </div>
      <p v-if="schemes.length === 0" class="placeholder">暂无术语表</p>
    </div>
  </div>
</template>
