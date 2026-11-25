<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import EmptyState from "../components/EmptyState.vue";
import PageHeader from "../components/PageHeader.vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface ToolEntry {
  tool_id: string;
  description?: string;
  source: string;
  data_classes: string[];
  requires_approval: boolean;
  granted_agents: { id: string; version: string }[];
}

interface ConnectorSpec {
  connector_id: string;
  tenant?: string | null;
  kind: string;
  base_url: string;
  enabled: boolean;
}

interface PeerEntry {
  peer: { peer_id: string; tenant: string; kind: string; enabled: boolean };
  grants: { agent_id: string; actions: string[] }[];
}

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "mcp", label: "MCP" },
  { key: "connector", label: "连接器" },
  { key: "function", label: "函数" },
  { key: "openapi", label: "OpenAPI" },
];

const SNIPPETS = [
  {
    key: "mcp",
    title: "接入 MCP 服务器",
    hint: "登记为 kind=mcp 的连接器后，它的工具会出现在工具目录里。",
    to: "/connectors",
    command:
      "adk-agent connectors register --id <id> --kind mcp --base-url https://mcp.example.com --auth-ref secret://<tenant>/<name> --connectors-dir ./connectors",
  },
  {
    key: "mcp-serve",
    title: "把 Agent 暴露为 MCP 服务",
    hint: "先导出 ADK_MCP_TOKEN，再按注册表的固定版本启动 streamable-http 端点。",
    to: "/registry",
    command:
      "ADK_MCP_TOKEN=your-token adk-agent serve --agent-ref <tenant>/<id>@<version> --transport streamable-http --host 127.0.0.1 --port 8766 --auth-token-env ADK_MCP_TOKEN",
  },
  {
    key: "a2a",
    title: "登记 A2A 对端",
    hint: "登记对端身份，再用 serve-a2a 发布端点。",
    to: "/peers",
    command: "adk-agent peers register --id <peer> --tenant <tenant> --kind service --peer-dir ./peers",
  },
  {
    key: "a2a-grant",
    title: "授权 A2A 对端",
    hint: "给对端授予读取或调用指定 Agent 的权限。",
    to: "/peers",
    command: "adk-agent peers grant --id <peer> --agent <agent-id> --actions read,invoke --peer-dir ./peers",
  },
];

const auth = useAuthStore();
const tools = ref<ToolEntry[]>([]);
const connectors = ref<ConnectorSpec[]>([]);
const peers = ref<PeerEntry[]>([]);
const toolsReady = ref(false);
const connectorsReady = ref(false);
const peersReady = ref(false);
const errors = ref("");
const filter = ref("all");
const copied = ref("");

const canTools = computed(() => auth.hasCapability("tools.read"));
const canConnectors = computed(() => auth.hasCapability("connectors.read"));
const canPeers = computed(() => auth.hasCapability("peers.read"));
const denied = computed(() => !canTools.value && !canConnectors.value && !canPeers.value);

const mcpConnectors = computed(
  () => connectors.value.filter((item) => item.kind === "mcp" && item.enabled),
);
const mcpServerCount = computed(
  () => connectors.value.filter((item) => item.kind === "mcp").length,
);
const mcpConnectorIds = computed(
  () => new Set(mcpConnectors.value.map((connector) => connector.connector_id)),
);

function isMcpTool(tool: ToolEntry): boolean {
  return (
    tool.source === "mcp" ||
    (tool.source === "connector" && mcpConnectorIds.value.has(tool.tool_id))
  );
}

const mcpTools = computed(() => tools.value.filter(isMcpTool));
const filteredTools = computed(() => {
  if (filter.value === "all") return tools.value;
  if (filter.value === "mcp") return tools.value.filter(isMcpTool);
  return tools.value.filter((tool) => tool.source === filter.value);
});

function joinClasses(classes: string[]): string {
  return classes.join(", ") || "-";
}

function grantsLabel(agents: { id: string }[]): string {
  return agents.length ? agents.map((agent) => agent.id).join(", ") : "-";
}

async function copy(command: string, key: string) {
  try {
    await navigator.clipboard.writeText(command);
    copied.value = key;
    window.setTimeout(() => {
      if (copied.value === key) copied.value = "";
    }, 2000);
  } catch {
    copied.value = "复制失败，请手动选择命令";
  }
}

onMounted(async () => {
  if (denied.value) return;
  const failures: string[] = [];
  if (canTools.value) {
    try {
      tools.value = await getJson<ToolEntry[]>("/api/tools");
      toolsReady.value = true;
    } catch {
      failures.push("工具目录");
    }
  }
  if (canConnectors.value) {
    try {
      connectors.value = await getJson<ConnectorSpec[]>("/api/connectors");
      connectorsReady.value = true;
    } catch {
      failures.push("连接器");
    }
  }
  if (canPeers.value) {
    try {
      peers.value = await getJson<PeerEntry[]>("/api/peers");
      peersReady.value = true;
    } catch {
      failures.push("A2A 对端");
    }
  }
  if (failures.length) errors.value = `${failures.join("、")}不可用`;
});
</script>

<template>
  <div class="panel">
    <PageHeader title="生态" description="MCP、A2A、连接器与可复用工具" />

    <p v-if="denied" class="placeholder">无访问权限</p>
    <template v-else>
      <p v-if="errors" class="login-msg">{{ errors }}</p>

      <div class="metric-grid">
        <div class="stat-card">
          <span class="stat-label">工具</span>
          <span class="stat-value">{{ canTools && toolsReady ? tools.length : "—" }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">MCP 工具</span>
          <span class="stat-value">{{ canTools && toolsReady && connectorsReady ? mcpTools.length : "—" }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">连接器</span>
          <span class="stat-value">{{ canConnectors && connectorsReady ? connectors.length : "—" }}</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">A2A 对端</span>
          <span class="stat-value">{{ canPeers && peersReady ? peers.length : "—" }}</span>
        </div>
      </div>

      <section class="recent-activity">
        <h2>接入引导</h2>
        <div class="guide-grid">
          <article v-for="snippet in SNIPPETS" :key="snippet.key" class="guide-card">
            <h3>{{ snippet.title }}</h3>
            <p>{{ snippet.hint }}</p>
            <pre>{{ snippet.command }}</pre>
            <div class="guide-actions">
              <button class="secondary" @click="copy(snippet.command, snippet.key)">
                {{ copied === snippet.key ? "已复制" : "复制命令" }}
              </button>
              <router-link :to="snippet.to" class="link">前往页面</router-link>
            </div>
          </article>
        </div>
        <p v-if="copied === '复制失败，请手动选择命令'" class="login-msg">{{ copied }}</p>
      </section>

      <section v-if="canTools && toolsReady" class="recent-activity">
        <h2>工具目录</h2>
        <p v-if="!connectorsReady" class="muted">
          连接器数据不可用或无权读取，MCP 筛选只覆盖静态目录条目。
        </p>
        <div class="filter-row">
          <button
            v-for="option in FILTERS"
            :key="option.key"
            class="filter"
            :class="{ active: filter === option.key }"
            @click="filter = option.key"
          >
            {{ option.label }}
          </button>
        </div>
        <div v-if="filteredTools.length" class="table-wrap">
  <table class="data-table">
          <thead>
            <tr>
              <th>工具 ID</th>
              <th>来源</th>
              <th>数据分级</th>
              <th>需审批</th>
              <th>授权 Agent</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="tool in filteredTools" :key="tool.tool_id">
              <td>{{ tool.tool_id }}</td>
              <td>{{ tool.source }}</td>
              <td>{{ joinClasses(tool.data_classes) }}</td>
              <td>{{ tool.requires_approval ? "yes" : "no" }}</td>
              <td>{{ grantsLabel(tool.granted_agents) }}</td>
            </tr>
          </tbody>
          </table>
        </div>
        <EmptyState v-else>暂无匹配的工具</EmptyState>
      </section>

      <section v-if="canConnectors && connectorsReady" class="recent-activity">
        <h2>连接器与 MCP 服务器</h2>
        <div v-if="connectors.length" class="table-wrap">
  <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>类型</th>
              <th>Base URL</th>
              <th>启用</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="connector in connectors" :key="connector.connector_id">
              <td>{{ connector.connector_id }}</td>
              <td>{{ connector.kind }}</td>
              <td>{{ connector.base_url }}</td>
              <td>{{ connector.enabled ? "yes" : "no" }}</td>
            </tr>
          </tbody>
          </table>
        </div>
        <EmptyState v-else>暂无连接器</EmptyState>
        <p class="muted">其中 MCP 服务器 {{ mcpServerCount }} 个（含已禁用）。</p>
      </section>

      <section v-if="canPeers && peersReady" class="recent-activity">
        <h2>A2A 对端</h2>
        <div v-if="peers.length" class="table-wrap">
  <table class="data-table">
          <thead>
            <tr>
              <th>对端 ID</th>
              <th>租户</th>
              <th>类型</th>
              <th>启用</th>
              <th>授权</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in peers" :key="entry.peer.peer_id">
              <td>{{ entry.peer.peer_id }}</td>
              <td>{{ entry.peer.tenant }}</td>
              <td>{{ entry.peer.kind }}</td>
              <td>{{ entry.peer.enabled ? "yes" : "no" }}</td>
              <td>{{ entry.grants.length }}</td>
            </tr>
          </tbody>
          </table>
        </div>
        <EmptyState v-else>暂无对端</EmptyState>
      </section>
    </template>
  </div>
</template>
