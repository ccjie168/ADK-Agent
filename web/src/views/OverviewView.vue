<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import EmptyState from "../components/EmptyState.vue";
import PageHeader from "../components/PageHeader.vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface Card {
  key: string;
  label: string;
  panel: string;
  value: number | null;
}

interface AuditEvent {
  action: string;
  target?: string;
  status?: string;
  timestamp?: string;
}

interface Sections {
  quick: boolean;
  cards: boolean;
  activity: boolean;
}

const PANEL_ROUTES: Record<string, string> = {
  approvals: "/approvals",
  registry: "/registry",
  tools: "/tools",
  grants: "/grants",
};

const STORAGE_KEY = "adk.home.sections";
const DEFAULT_SECTIONS: Sections = { quick: true, cards: true, activity: true };
const ACTIONS = [
  { label: "注册 Agent", to: "/import", capability: "registry.publish", hint: "从清单创建新版本" },
  { label: "加载版本", to: "/registry", capability: "registry.load", hint: "把已发布版本装进运行时" },
  { label: "处理审批", to: "/approvals", capability: "approvals.read", hint: "待处理的人机确认" },
  { label: "安全视图", to: "/security", capability: "ops.read", hint: "审计链、密钥与扫描" },
];

function loadSections(): Sections {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_SECTIONS };
    const parsed = JSON.parse(raw) as Partial<Sections>;
    return {
      quick: typeof parsed.quick === "boolean" ? parsed.quick : true,
      cards: typeof parsed.cards === "boolean" ? parsed.cards : true,
      activity: typeof parsed.activity === "boolean" ? parsed.activity : true,
    };
  } catch {
    return { ...DEFAULT_SECTIONS };
  }
}

const auth = useAuthStore();
const router = useRouter();
const cards = ref<Card[]>([]);
const events = ref<AuditEvent[]>([]);
const activityError = ref("");
const loading = ref(false);
const customizing = ref(false);
const sections = ref<Sections>(loadSections());
const draft = reactive<Sections>(loadSections());
const denied = computed(() => !auth.hasCapability("ops.read"));
const actions = computed(() => ACTIONS.filter((action) => auth.hasCapability(action.capability)));
const canAudit = computed(() => auth.hasCapability("audit.read"));

function openCustomize() {
  Object.assign(draft, sections.value);
  customizing.value = true;
}

function saveSections() {
  sections.value = { ...draft };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sections.value));
  customizing.value = false;
}

function resetSections() {
  Object.assign(draft, DEFAULT_SECTIONS);
}

function displayValue(value: number | null): string {
  return value === null ? "未配置" : String(value);
}

function openPanel(panel: string) {
  void router.push(PANEL_ROUTES[panel] ?? "/");
}

function timeOf(event: AuditEvent): string {
  return event.timestamp ? new Date(event.timestamp).toLocaleString("zh-CN") : "—";
}

onMounted(async () => {
  if (denied.value) return;
  loading.value = true;
  try {
    const data = await getJson<{ cards: Card[] }>("/api/overview");
    cards.value = data.cards ?? [];
  } catch {
    cards.value = [];
  } finally {
    loading.value = false;
  }
  if (!canAudit.value) return;
  try {
    const rows = await getJson<AuditEvent[]>("/api/audit?limit=6");
    events.value = rows.slice(0, 6);
  } catch {
    activityError.value = "审计事件不可用";
  }
});
</script>

<template>
  <div class="panel">
    <PageHeader title="总览" description="平台运行概况与常用入口">
      <button class="secondary" @click="openCustomize">自定义首页</button>
    </PageHeader>

    <p v-if="denied" class="placeholder">无访问权限</p>
    <template v-else>
      <section v-if="customizing" class="customize">
        <h2>首页区块</h2>
        <label><input v-model="draft.quick" type="checkbox" /> 快捷操作</label>
        <label><input v-model="draft.cards" type="checkbox" /> 指标卡</label>
        <label><input v-model="draft.activity" type="checkbox" /> 最近活动</label>
        <div class="customize-actions">
          <button class="primary" @click="saveSections">保存</button>
          <button class="secondary" @click="resetSections">恢复默认</button>
          <button class="link" @click="customizing = false">取消</button>
        </div>
      </section>

      <section v-if="sections.quick && actions.length" class="quick-actions">
        <router-link v-for="action in actions" :key="action.to" :to="action.to" class="quick-action">
          <span class="quick-label">{{ action.label }}</span>
          <span class="quick-hint">{{ action.hint }}</span>
        </router-link>
      </section>

      <div v-if="sections.cards">
        <p v-if="loading" class="placeholder">加载中…</p>
        <div v-else-if="cards.length" class="metric-grid">
          <div
            v-for="card in cards"
            :key="card.key"
            class="stat-card"
            role="button"
            tabindex="0"
            @click="openPanel(card.panel)"
            @keydown.enter="openPanel(card.panel)"
            @keydown.space.prevent="openPanel(card.panel)"
          >
            <div class="stat-label">{{ card.label }}</div>
            <div class="stat-value">{{ displayValue(card.value) }}</div>
          </div>
        </div>
        <EmptyState v-else>暂无可展示的指标</EmptyState>
      </div>

      <section v-if="sections.activity" class="recent-activity">
        <h2>最近活动</h2>
        <p v-if="!canAudit" class="placeholder">无权查看审计事件</p>
        <p v-else-if="activityError" class="login-msg">{{ activityError }}</p>
        <table v-else-if="events.length" class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>动作</th>
              <th>对象</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(event, index) in events" :key="index">
              <td>{{ timeOf(event) }}</td>
              <td>{{ event.action }}</td>
              <td>{{ event.target ?? "—" }}</td>
              <td>{{ event.status ?? "—" }}</td>
            </tr>
          </tbody>
        </table>
        <EmptyState v-else>暂无审计事件</EmptyState>
      </section>
    </template>
  </div>
</template>
