<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

type Tone = "good" | "bad" | "warn" | "muted";

interface RegistryEntry {
  id: string;
  tenant?: string;
  source: string;
  version?: string;
  digest?: string;
  description?: string;
  published_at?: string;
  has_eval_report?: boolean;
  artifact?: { status?: string } | null;
  lifecycle?: { status?: string } | null;
  label?: string;
  peer_id?: string;
  enabled?: boolean;
  trust?: { status?: string };
}

const BADGE_TONES: Record<string, Tone> = {
  verified: "good",
  pinned: "good",
  eval: "good",
  published: "good",
  approved: "good",
  untrusted: "bad",
  changed: "bad",
  retired: "bad",
  denied: "bad",
  unsigned: "warn",
  unreachable: "warn",
  deprecated: "warn",
  expired: "warn",
  cancelled: "muted",
};

const auth = useAuthStore();
const entries = ref<RegistryEntry[]>([]);
const manifestDraft = ref("");
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("registry.read"));
const canLoad = computed(() => auth.hasCapability("registry.load"));
const canPublish = computed(() => auth.hasCapability("registry.publish"));

function badgesOf(entry: RegistryEntry): string[] {
  const local = entry.source !== "remote";
  const badges = [local ? "local" : "remote"];
  if (local) {
    if (entry.artifact) badges.push(entry.artifact.status || "unknown");
    badges.push(entry.has_eval_report ? "eval" : "no eval");
    badges.push(entry.lifecycle?.status || "published");
  } else {
    badges.push(entry.trust?.status || "unknown");
    if (!entry.enabled) badges.push("disabled");
  }
  return badges;
}

function toneOf(label: string): Tone {
  return BADGE_TONES[label] ?? "muted";
}

function metaOf(entry: RegistryEntry): string {
  if (entry.source !== "remote") {
    const published = String(entry.published_at ?? "").replace("T", " ").slice(0, 19);
    const digest = String(entry.digest ?? "").replace(/^sha256:/, "").slice(0, 12);
    return `${published} ${digest}`.trim();
  }
  return `peer ${entry.peer_id ?? ""}`;
}

function subOf(entry: RegistryEntry): string {
  if (entry.source !== "remote") return entry.version ?? "";
  return entry.label ?? "";
}

async function reload() {
  try {
    entries.value = await getJson<RegistryEntry[]>("/api/registry");
  } catch {
    error.value = "registry unavailable";
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

const LOAD_ERRORS: Record<string, string> = {
  name_conflict: "名称冲突：请先卸载同名 Agent",
  version_retired: "版本已退役，不能加载",
  artifact_missing: "工件缺失，无法加载",
  artifact_untrusted: "工件未通过信任校验",
  artifact_trust_unavailable: "信任校验不可用",
  sandbox_unavailable: "沙箱不可用",
  tool_mediation_unavailable: "需要工具网关后才可加载",
  load_limit: "已达加载数量上限",
  not_found: "注册表中找不到该版本",
};

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? "";
  } catch {
    return "";
  }
}

async function loadAgent(entry: RegistryEntry) {
  const response = await post("/api/registry/load", {
    tenant: entry.tenant ?? auth.principal?.tenant ?? "local",
    id: entry.id,
    version: entry.version,
  });
  if (response === null) return;
  if (response.ok) {
    message.value = `已加载 ${entry.id}@${entry.version}`;
    return;
  }
  message.value = `加载失败: ${LOAD_ERRORS[await errorCode(response)] ?? response.status}`;
}

async function unloadAgent(entry: RegistryEntry) {
  const response = await post("/api/registry/unload", { name: entry.id });
  if (response === null) return;
  if (response.ok) message.value = `已卸载 ${entry.id}`;
  else if (response.status === 409) message.value = "无法卸载：该 Agent 由启动参数加载";
  else message.value = `卸载失败: ${response.status}`;
}

async function registerManifest() {
  let parsed: unknown;
  try {
    parsed = JSON.parse(manifestDraft.value);
  } catch {
    message.value = "JSON 格式无效";
    return;
  }
  const response = await post("/api/import/agent", parsed);
  if (response === null) return;
  if (response.ok) {
    const body = (await response.json()) as { id: string; version: string };
    message.value = `已注册 ${body.id}@${body.version}`;
    manifestDraft.value = "";
    await reload();
    return;
  }
  if (response.status === 400) message.value = "清单无效";
  else if (response.status === 403) message.value = "租户不允许";
  else message.value = `注册失败: ${response.status}`;
}

onMounted(async () => {
  if (denied.value) return;
  await reload();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="注册表" description="已发布版本与市场入口" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <div class="card-grid">
        <div
          v-for="entry in entries"
          :key="entry.source + ':' + entry.id"
          class="card"
        >
          <div class="card-head">
            {{ entry.id }}
            <span v-if="subOf(entry)" class="muted">{{ subOf(entry) }}</span>
          </div>
          <div v-if="entry.source !== 'remote' && entry.description" class="card-desc">
            {{ entry.description }}
          </div>
          <div class="card-badges">
            <span
              v-for="badge in badgesOf(entry)"
              :key="badge"
              class="badge"
              :class="{
                bad: toneOf(badge) === 'bad',
                warn: toneOf(badge) === 'warn',
                muted: toneOf(badge) === 'muted',
              }"
            >
              {{ badge }}
            </span>
          </div>
          <div class="card-meta">{{ metaOf(entry) }}</div>
          <div v-if="canLoad && entry.source !== 'remote' && entry.version" class="row">
            <button class="link" @click="loadAgent(entry)">加载</button>
            <button class="link" @click="unloadAgent(entry)">卸载</button>
          </div>
        </div>
        <p v-if="entries.length === 0" class="placeholder">暂无已注册 Agent</p>
      </div>
      <template v-if="canPublish">
        <h2>注册 Agent 清单</h2>
        <textarea
          v-model="manifestDraft"
          class="policy-editor"
          rows="10"
          spellcheck="false"
          placeholder='{"id": "bot_c", "version": "1.0.0", ...}'
        />
        <div class="row">
          <button class="primary" @click="registerManifest">注册</button>
        </div>
      </template>
    </template>
  </div>
</template>
