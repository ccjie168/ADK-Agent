<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface Card {
  key: string;
  label: string;
  panel: string;
  value: number | null;
}

const PANEL_ROUTES: Record<string, string> = {
  approvals: "/approvals",
  registry: "/registry",
  tools: "/tools",
  grants: "/grants",
};

const auth = useAuthStore();
const router = useRouter();
const cards = ref<Card[]>([]);
const denied = computed(() => !auth.hasCapability("ops.read"));

function routeFor(panel: string): string {
  return PANEL_ROUTES[panel] ?? "/";
}

function displayValue(value: number | null): string {
  return value === null ? "未配置" : String(value);
}

function openPanel(panel: string) {
  void router.push(routeFor(panel));
}

onMounted(async () => {
  if (denied.value) return;
  try {
    const data = await getJson<{ cards: Card[] }>("/api/overview");
    cards.value = data.cards ?? [];
  } catch {
    cards.value = [];
  }
});
</script>

<template>
  <div class="panel">
    <h1>总览</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <div v-else class="metric-grid">
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
  </div>
</template>
