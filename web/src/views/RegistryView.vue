<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

type Tone = "good" | "bad" | "warn" | "muted";

interface RegistryEntry {
  id: string;
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
const error = ref("");
const denied = computed(() => !auth.hasCapability("registry.read"));

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

onMounted(async () => {
  if (denied.value) return;
  try {
    entries.value = await getJson<RegistryEntry[]>("/api/registry");
  } catch {
    error.value = "registry unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>注册表</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <div v-else class="card-grid">
      <div v-for="entry in entries" :key="entry.source + ':' + entry.id" class="card">
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
            :class="{ bad: toneOf(badge) === 'bad', warn: toneOf(badge) === 'warn', muted: toneOf(badge) === 'muted' }"
          >
            {{ badge }}
          </span>
        </div>
        <div class="card-meta">{{ metaOf(entry) }}</div>
      </div>
      <p v-if="entries.length === 0" class="placeholder">暂无已注册 Agent</p>
    </div>
  </div>
</template>
