<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface ModelSummary {
  recent_calls: number;
  aliases: string[];
  fallbacks: number;
}

const auth = useAuthStore();
const summary = ref<ModelSummary | null>(null);
const defaultModel = ref("");
const draftModel = ref("");
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("model.read"));
const canWrite = computed(() => auth.hasCapability("model.write"));

function aliasesLabel(aliases: string[] | undefined): string {
  return aliases && aliases.length ? aliases.join(", ") : "—";
}

async function loadDefaultModel() {
  try {
    const body = await getJson<{ model: string }>("/api/model-config");
    defaultModel.value = body.model;
    draftModel.value = body.model;
  } catch {
    message.value = "model config unavailable";
  }
}

async function saveDefaultModel() {
  const model = draftModel.value.trim();
  if (!model) {
    message.value = "需要模型名";
    return;
  }
  const response = await apiFetch("/api/model-config", {
    method: "PUT",
    body: JSON.stringify({ model }),
  });
  if (response.ok) {
    defaultModel.value = model;
    message.value = "已保存";
    return;
  }
  message.value = response.status === 400 ? "模型名无效" : `保存失败: ${response.status}`;
}

onMounted(async () => {
  if (denied.value) return;
  try {
    summary.value = await getJson<ModelSummary>("/api/model");
  } catch {
    error.value = "model unavailable";
  }
  await loadDefaultModel();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="模型" description="调用、别名与默认模型" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
      <div v-if="summary" class="metric-grid">
        <div class="stat-card">
          <div class="stat-label">最近调用</div>
          <div class="stat-value">{{ summary.recent_calls }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">使用别名</div>
          <div class="stat-value">{{ aliasesLabel(summary.aliases) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">降级次数</div>
          <div class="stat-value">{{ summary.fallbacks }}</div>
        </div>
      </div>
      <p v-else class="placeholder">暂无模型数据</p>

      <h2>默认模型</h2>
      <p class="placeholder">当前: {{ defaultModel || "未配置" }}</p>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <div v-if="canWrite" class="row">
        <input
          v-model="draftModel"
          class="grow"
          placeholder="litellm:deepseek/deepseek-v4-pro"
          autocomplete="off"
        />
        <button class="primary" @click="saveDefaultModel">保存</button>
      </div>
    </template>
  </div>
</template>
