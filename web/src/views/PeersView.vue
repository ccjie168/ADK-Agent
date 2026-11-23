<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface PeerGrant {
  agent_id: string;
  actions: string[];
}

interface PeerEntry {
  peer: {
    peer_id: string;
    tenant: string;
    subject?: string;
    kind: string;
    enabled: boolean;
  };
  grants: PeerGrant[];
}

const auth = useAuthStore();
const peers = ref<PeerEntry[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("peers.read"));

function grantsLabel(grants: PeerGrant[]): string {
  const text = grants
    .map((grant) => `${grant.agent_id}:${grant.actions.join("+")}`)
    .join(", ");
  return text || "-";
}

onMounted(async () => {
  if (denied.value) return;
  try {
    peers.value = await getJson<PeerEntry[]>("/api/peers");
  } catch {
    error.value = "peers unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>对端</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>对端 ID</th>
          <th>租户</th>
          <th>主体</th>
          <th>类型</th>
          <th>启用</th>
          <th>授权</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="entry in peers" :key="entry.peer.peer_id">
          <td>{{ entry.peer.peer_id }}</td>
          <td>{{ entry.peer.tenant }}</td>
          <td>{{ entry.peer.subject ?? "" }}</td>
          <td>{{ entry.peer.kind }}</td>
          <td>{{ entry.peer.enabled ? "yes" : "no" }}</td>
          <td>{{ grantsLabel(entry.grants) }}</td>
        </tr>
        <tr v-if="peers.length === 0">
          <td colspan="6" class="placeholder">暂无对端</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
