<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

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
const reason = ref("");
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("approvals.read"));
const canDecide = computed(() => auth.hasCapability("approvals.decide"));

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

async function reload() {
  try {
    approvals.value = await getJson<ApprovalRequest[]>("/api/approvals");
  } catch {
    error.value = "approvals unavailable";
  }
}

async function decide(request: ApprovalRequest, approved: boolean) {
  let response: Response;
  try {
    response = await apiFetch(`/api/approvals/${encodeURIComponent(request.request_id)}`, {
      method: "POST",
      body: JSON.stringify({ approved, reason: reason.value }),
    });
  } catch {
    message.value = "决定失败: 网络错误";
    return;
  }
  if (response.ok) {
    message.value = approved ? "已批准" : "已拒绝";
    reason.value = "";
    await reload();
    return;
  }
  const codes: Record<string, string> = {
    approval_not_found: "审批不存在",
    approval_unavailable: "审批存储不可用",
    tenant_forbidden: "租户不允许",
    policy_denied: "策略拒绝该决定",
  };
  message.value = `决定失败: ${codes[await errorCode(response)] ?? response.status}`;
}

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? "";
  } catch {
    return "";
  }
}

onMounted(async () => {
  if (denied.value) return;
  await reload();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="审批" description="待处理与历史的人机审批" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
    <p v-if="message" class="login-msg">{{ message }}</p>
    <div v-if="canDecide" class="row">
      <input v-model="reason" class="grow" placeholder="决定理由（可选）" autocomplete="off" />
    </div>
    <div class="table-wrap">
  <table class="data-table">
      <thead>
        <tr>
          <th>请求 ID</th>
          <th>步骤</th>
          <th>Agent</th>
          <th>理由</th>
          <th>提交时间</th>
          <th>到期</th>
          <th v-if="canDecide" />
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
          <td v-if="canDecide" class="row">
            <button class="link" @click="decide(request, true)">批准</button>
            <button class="link" @click="decide(request, false)">拒绝</button>
          </td>
        </tr>
        <tr v-if="approvals.length === 0">
          <td :colspan="canDecide ? 7 : 6" class="placeholder">没有待决审批。</td>
        </tr>
      </tbody>
      </table>
    </div>
    </template>
  </div>
</template>
