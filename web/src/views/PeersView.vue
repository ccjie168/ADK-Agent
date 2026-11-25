<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";
import EmptyState from "../components/EmptyState.vue";

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

const KINDS = ["service", "agent", "human"];

const auth = useAuthStore();
const peers = ref<PeerEntry[]>([]);
const peerDraft = ref({ peer_id: "", tenant: "", subject: "", kind: "service" });
const remoteDraft = ref({
  remote_id: "",
  tenant: "",
  peer_id: "",
  agent_card_url: "",
  credential_ref: "",
  label: "",
});
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("peers.read"));
const canManage = computed(() => auth.hasCapability("peers.manage"));

function grantsLabel(grants: PeerGrant[]): string {
  const text = grants
    .map((grant) => `${grant.agent_id}:${grant.actions.join("+")}`)
    .join(", ");
  return text || "-";
}

async function reload() {
  try {
    peers.value = await getJson<PeerEntry[]>("/api/peers");
  } catch {
    error.value = "对端存储不可用：配置 --peer-dir 或 --peer-db 后刷新";
  }
}

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? "";
  } catch {
    return "";
  }
}

async function post(path: string, body: unknown): Promise<Response | null> {
  try {
    return await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
  } catch {
    message.value = "请求失败: 网络错误";
    return null;
  }
}

async function registerPeer() {
  const response = await post("/api/peers", {
    peer_id: peerDraft.value.peer_id.trim(),
    tenant: peerDraft.value.tenant.trim(),
    subject: peerDraft.value.subject.trim(),
    kind: peerDraft.value.kind,
  });
  if (response === null) return;
  if (response.ok) {
    message.value = `已注册 ${peerDraft.value.peer_id.trim()}`;
    await reload();
    return;
  }
  const codes: Record<string, string> = {
    invalid_peer: "对端定义无效",
    peer_tenant_immutable: "该对端已属于其他租户",
    peer_store_unavailable: "对端存储不可用",
  };
  message.value = `注册失败: ${codes[await errorCode(response)] ?? response.status}`;
}

async function disablePeer(entry: PeerEntry) {
  const response = await post(
    `/api/peers/${encodeURIComponent(entry.peer.peer_id)}/disable`,
    {},
  );
  if (response === null) return;
  if (response.ok) {
    message.value = `已禁用 ${entry.peer.peer_id}`;
    await reload();
    return;
  }
  const codes: Record<string, string> = {
    peer_not_found: "对端不存在",
    tenant_forbidden: "租户不允许",
    peer_store_unavailable: "对端存储不可用",
  };
  message.value = `禁用失败: ${codes[await errorCode(response)] ?? response.status}`;
}

async function registerRemote() {
  const body: Record<string, unknown> = {
    remote_id: remoteDraft.value.remote_id.trim(),
    tenant: remoteDraft.value.tenant.trim(),
    peer_id: remoteDraft.value.peer_id.trim(),
    agent_card_url: remoteDraft.value.agent_card_url.trim(),
    label: remoteDraft.value.label.trim(),
  };
  if (remoteDraft.value.credential_ref.trim()) {
    body.credential_ref = remoteDraft.value.credential_ref.trim();
  }
  const response = await post("/api/remote-agents", body);
  if (response === null) return;
  if (response.ok) {
    message.value = `已登记远端 ${remoteDraft.value.remote_id.trim()}`;
    return;
  }
  const codes: Record<string, string> = {
    invalid_remote_agent: "远端定义无效（卡片地址需 https 或 loopback）",
    peer_not_found: "对端不存在",
    tenant_mismatch: "租户与对端不一致",
    secret_unavailable: "对端凭据不可用",
    remote_agent_tenant_immutable: "该远端已属于其他租户",
    remote_agent_store_unavailable: "远端目录存储不可用",
    peer_store_unavailable: "对端存储不可用",
    card_unreachable: "无法访问对端卡片地址",
    card_unauthorized: "对端卡片地址拒绝访问（凭据无效？）",
    card_too_large: "对端卡片超出大小上限",
    card_invalid: "对端返回的卡片无法解析",
    card_name_mismatch: "卡片名称与远端 ID 不一致",
  };
  message.value = `登记失败: ${codes[await errorCode(response)] ?? response.status}`;
}

onMounted(async () => {
  if (denied.value) return;
  await reload();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="对端" description="A2A 对端与授权" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <EmptyState
        v-if="peers.length === 0"
        description="对端用于 A2A 互通；用 adk-agent peers register 登记对端身份后再授权。"
      >暂无对端</EmptyState>
      <div v-else class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>对端 ID</th>
              <th>租户</th>
              <th>主体</th>
              <th>类型</th>
              <th>启用</th>
              <th>授权</th>
              <th />
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
              <td>
                <button
                  v-if="canManage && entry.peer.enabled"
                  class="link"
                  @click="disablePeer(entry)"
                >
                  禁用
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <template v-if="canManage">
        <h2>注册对端</h2>
        <div class="row">
          <input v-model="peerDraft.peer_id" class="grow" placeholder="对端 ID" />
          <input v-model="peerDraft.tenant" class="grow" placeholder="租户" />
        </div>
        <div class="row">
          <input v-model="peerDraft.subject" class="grow" placeholder="主体" />
          <select v-model="peerDraft.kind">
            <option v-for="kind in KINDS" :key="kind" :value="kind">{{ kind }}</option>
          </select>
          <button class="primary" @click="registerPeer">注册对端</button>
        </div>

        <h2>登记远端 Agent</h2>
        <p class="placeholder">登记时服务端会抓取 Agent 卡片；凭据引用可选（secret:// 形式）。</p>
        <div class="row">
          <input v-model="remoteDraft.remote_id" class="grow" placeholder="远端 ID" />
          <input v-model="remoteDraft.tenant" class="grow" placeholder="租户" />
          <input v-model="remoteDraft.peer_id" class="grow" placeholder="对端 ID" />
        </div>
        <div class="row">
          <input
            v-model="remoteDraft.agent_card_url"
            class="grow"
            placeholder="https://peer.example.com/.well-known/agent.json"
          />
          <input
            v-model="remoteDraft.credential_ref"
            class="grow"
            placeholder="secret://tenant/name（可选）"
          />
          <input v-model="remoteDraft.label" class="grow" placeholder="标签" />
        </div>
        <div class="row">
          <button class="primary" @click="registerRemote">登记远端</button>
        </div>
      </template>
    </template>
  </div>
</template>
