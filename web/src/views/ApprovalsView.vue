<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface ApprovalRequest {
  request_id: string;
  step_id: string;
  agent_ref?: { id: string } | null;
  reason?: string;
  requested_at?: string | null;
  expires_at?: string | null;
}

interface ExpiryLabel {
  text: string;
  soon: boolean;
}

const auth = useAuthStore();
const approvals = ref<ApprovalRequest[]>([]);
const error = ref("");
const denied = computed(() => !auth.hasCapability("approvals.read"));

function expiryLabel(value: string | null | undefined): ExpiryLabel {
  if (!value) return { text: "no deadline", soon: false };
  const left = Date.parse(value) - Date.now();
  if (Number.isNaN(left)) return { text: value, soon: false };
  if (left <= 0) return { text: "expired", soon: true };
  const minutes = Math.ceil(left / 60000);
  if (minutes < 60) return { text: `${minutes}m left`, soon: minutes <= 10 };
  const hours = Math.floor(minutes / 60);
  return { text: `${hours}h ${minutes % 60}m left`, soon: false };
}

function requestedLabel(value: string | null | undefined): string {
  return String(value ?? "").replace("T", " ").slice(0, 19);
}

onMounted(async () => {
  if (denied.value) return;
  try {
    approvals.value = await getJson<ApprovalRequest[]>("/api/approvals");
  } catch {
    error.value = "approvals unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>审批</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>请求 ID</th>
          <th>步骤</th>
          <th>Agent</th>
          <th>理由</th>
          <th>提交时间</th>
          <th>到期</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="request in approvals" :key="request.request_id">
          <td>{{ String(request.request_id).slice(0, 16) }}</td>
          <td>{{ request.step_id }}</td>
          <td>{{ request.agent_ref?.id ?? "-" }}</td>
          <td>{{ request.reason ?? "" }}</td>
          <td>{{ requestedLabel(request.requested_at) }}</td>
          <td>
            <span :class="['expiry', { soon: expiryLabel(request.expires_at).soon }]">
              {{ expiryLabel(request.expires_at).text }}
            </span>
          </td>
        </tr>
        <tr v-if="approvals.length === 0">
          <td colspan="6" class="placeholder">没有待决审批。</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
