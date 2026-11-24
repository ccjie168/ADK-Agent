<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface AgentInfo {
  name: string;
  description: string;
}

interface SessionInfo {
  session_id: string;
  last_update_time: string | null;
}

const auth = useAuthStore();
const agents = ref<AgentInfo[]>([]);
const selectedAgent = ref("");
const sessions = ref<SessionInfo[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("sessions.read"));

function updatedLabel(value: string | null): string {
  return String(value ?? "").replace("T", " ").slice(0, 19);
}

async function loadSessions() {
  if (!selectedAgent.value) {
    sessions.value = [];
    return;
  }
  try {
    sessions.value = await getJson<SessionInfo[]>(
      `/api/sessions?agent=${encodeURIComponent(selectedAgent.value)}`,
    );
  } catch {
    error.value = "sessions unavailable";
  }
}

onMounted(async () => {
  if (denied.value) return;
  try {
    agents.value = await getJson<AgentInfo[]>("/api/agents");
    if (agents.value.length) {
      selectedAgent.value = agents.value[0].name;
      await loadSessions();
    }
  } catch {
    error.value = "agents unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <PageHeader title="会话" description="会话列表" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <template v-else>
      <label class="select-row">
        选择 Agent
        <select v-model="selectedAgent" @change="loadSessions">
          <option v-for="agent in agents" :key="agent.name" :value="agent.name">
            {{ agent.name }}
          </option>
        </select>
      </label>
      <p v-if="error" class="login-msg">{{ error }}</p>
      <table class="data-table">
        <thead>
          <tr>
            <th>会话 ID</th>
            <th>最后更新</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="session in sessions" :key="session.session_id">
            <td>{{ session.session_id }}</td>
            <td>{{ updatedLabel(session.last_update_time) }}</td>
          </tr>
          <tr v-if="sessions.length === 0">
            <td colspan="2" class="placeholder">暂无会话</td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
