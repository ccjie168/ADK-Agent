<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";
import EmptyState from "../components/EmptyState.vue";

interface AuditEvent {
  action: string;
  target?: string;
  status?: string;
  latency_ms?: number | null;
  run_id?: string;
  trace_id?: string;
}

const auth = useAuthStore();
const events = ref<AuditEvent[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("audit.read"));

function lineOf(event: AuditEvent): string {
  const latency = event.latency_ms ?? "-";
  const run = String(event.run_id ?? "").slice(0, 8);
  const trace = String(event.trace_id ?? "").slice(0, 8);
  return `${event.action} ${event.target ?? ""} ${event.status ?? ""} ${latency}ms run=${run} trace=${trace}`;
}

onMounted(async () => {
  if (denied.value) return;
  try {
    const rows = await getJson<AuditEvent[]>("/api/audit?limit=100");
    events.value = rows.slice().reverse();
  } catch {
    error.value = "audit unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <PageHeader title="审计" description="共享审计事件" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <EmptyState v-else-if="events.length === 0">暂无审计事件</EmptyState>
    <div v-else class="audit-log">
      <div v-for="(event, index) in events" :key="index" class="audit-line">
        {{ lineOf(event) }}
      </div>
    </div>
  </div>
</template>
