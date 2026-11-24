<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface ArtifactInfo {
  digest: string;
  size: number;
  key_id: string | null;
  status: string;
}

interface LifecycleInfo {
  status: string;
  updated_at?: string;
  updated_by?: string;
  reason?: string;
}

interface TrustInfo {
  status: string;
}

interface RegistryEntry {
  tenant: string;
  id: string;
  source: "local" | "remote";
  version?: string;
  description?: string;
  label?: string;
  published_at?: string;
  has_eval_report?: boolean;
  artifact?: ArtifactInfo | null;
  lifecycle?: LifecycleInfo;
  trust?: TrustInfo;
  peer_id?: string;
}

interface AgentGroup {
  id: string;
  description: string;
  entries: RegistryEntry[];
}

const auth = useAuthStore();
const entries = ref<RegistryEntry[]>([]);
const tenantDraft = ref("");
const activeTenant = ref("");
const evalReport = ref<{ title: string; body: string } | null>(null);
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("registry.read"));
const isAdmin = computed(() => Boolean(auth.principal?.roles?.includes("admin")));

const agents = computed<AgentGroup[]>(() => {
  const groups = new Map<string, AgentGroup>();
  for (const entry of entries.value) {
    const group = groups.get(entry.id) ?? {
      id: entry.id,
      description: entry.description ?? entry.label ?? "",
      entries: [],
    };
    group.entries.push(entry);
    groups.set(entry.id, group);
  }
  return [...groups.values()].sort((a, b) => a.id.localeCompare(b.id));
});

const lifecycleCounts = computed(() => {
  const counts: Record<string, number> = { published: 0, deprecated: 0, retired: 0 };
  for (const entry of entries.value) {
    const status = entry.lifecycle?.status;
    if (status && status in counts) counts[status] += 1;
  }
  return counts;
});

const localCount = computed(() => entries.value.filter((entry) => entry.source === "local").length);
const remoteCount = computed(() => entries.value.length - localCount.value);
const lifecycleTotal = computed(() =>
  Object.values(lifecycleCounts.value).reduce((sum, value) => sum + value, 0),
);

function barWidth(count: number): string {
  if (lifecycleTotal.value === 0) return "0%";
  return `${Math.round((count / lifecycleTotal.value) * 100)}%`;
}

function artifactStatus(entry: RegistryEntry): string {
  if (entry.source === "remote") return entry.trust?.status ?? "unknown";
  return entry.artifact?.status ?? "none";
}

async function load(tenant?: string) {
  error.value = "";
  const query = tenant ? `?tenant=${encodeURIComponent(tenant)}` : "";
  try {
    entries.value = await getJson<RegistryEntry[]>(`/api/registry${query}`);
    activeTenant.value = tenant ?? "";
  } catch {
    error.value = "registry unavailable";
  }
}

async function showEval(entry: RegistryEntry) {
  if (!entry.version) return;
  const tenant = entry.tenant || activeTenant.value || auth.principal?.tenant || "";
  const path = `/api/registry/${encodeURIComponent(tenant)}/${encodeURIComponent(entry.id)}/${encodeURIComponent(entry.version)}/eval`;
  try {
    const report = await getJson<unknown>(path);
    evalReport.value = {
      title: `${entry.id}@${entry.version} 评测报告`,
      body: JSON.stringify(report, null, 2),
    };
  } catch {
    message.value = "评测报告不可用";
  }
}

onMounted(async () => {
  if (denied.value) return;
  await load();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="Agent 中心" description="注册、版本与生命周期" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
      <div v-if="isAdmin" class="toolbar">
        <input
          v-model="tenantDraft"
          class="grow"
          placeholder="租户（留空为当前租户）"
          autocomplete="off"
        />
        <button class="primary" @click="load(tenantDraft.trim())">切换租户</button>
      </div>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <p v-if="activeTenant" class="placeholder">正在查看租户 {{ activeTenant }}</p>
      <div class="metric-grid">
        <div class="stat-card">
          <span class="stat-label">Agent</span>
          <span class="stat-value">{{ agents.length }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">版本</span>
          <span class="stat-value">{{ localCount }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">发布中</span>
          <span class="stat-value">{{ lifecycleCounts.published }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">已弃用 / 已退役</span>
          <span class="stat-value">
            {{ lifecycleCounts.deprecated }} / {{ lifecycleCounts.retired }}
          </span>
        </div>
        <div class="stat-card">
          <span class="stat-label">远端</span>
          <span class="stat-value">{{ remoteCount }}</span>
        </div>
      </div>

      <h2>生命周期分布</h2>
      <div class="lifecycle-bars">
        <div v-for="(count, status) in lifecycleCounts" :key="status" class="lifecycle-row">
          <span class="lifecycle-label">{{ status }}</span>
          <span class="lifecycle-bar" :style="{ width: barWidth(count) }" />
          <span class="lifecycle-count">{{ count }}</span>
        </div>
      </div>

      <h2>Agent 旅程</h2>
      <p v-if="agents.length === 0" class="placeholder">暂无 Agent</p>
      <section v-for="agent in agents" :key="agent.id" class="agent-card">
        <header>
          <strong>{{ agent.id }}</strong>
          <span class="placeholder">{{ agent.description }}</span>
        </header>
        <table>
          <thead>
            <tr>
              <th>版本</th>
              <th>生命周期</th>
              <th>评测</th>
              <th>工件 / 信任</th>
              <th>发布时间</th>
              <th>来源</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="(entry, index) in agent.entries" :key="entry.id + ':' + index">
              <td>{{ entry.version ?? "—" }}</td>
              <td>{{ entry.lifecycle?.status ?? "—" }}</td>
              <td>{{ entry.has_eval_report ? "有" : "无" }}</td>
              <td>{{ artifactStatus(entry) }}</td>
              <td>{{ entry.published_at ?? "—" }}</td>
              <td>{{ entry.source === "remote" ? `remote · ${entry.peer_id ?? ""}` : "local" }}</td>
              <td>
                <button
                  v-if="entry.has_eval_report"
                  class="link"
                  @click="showEval(entry)"
                >
                  评测报告
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <template v-if="evalReport">
        <h2>{{ evalReport.title }}</h2>
        <pre class="policy-view">{{ evalReport.body }}</pre>
        <div class="row">
          <button class="link" @click="evalReport = null">关闭</button>
        </div>
      </template>
    </template>
  </div>
</template>
