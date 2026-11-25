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

interface ModelProvider {
  provider_id: string;
  kind: string;
  model: string;
  base_url: string | null;
  secret_ref: string | null;
  enabled: boolean;
  updated_at: string;
  updated_by: string;
  key_configured: boolean;
  key_hint: string | null;
}

const KINDS = ["litellm", "gemini", "claude", "vertex"];
const PROVIDER_ERRORS: Record<string, string> = {
  invalid_provider: "提供方配置无效",
  provider_not_found: "提供方不存在",
  model_key_entry_disabled: "密钥录入未开启",
  model_key_entry_unavailable: "密钥后端不可用",
  invalid_key: "密钥格式无效",
  forbidden: "无写入权限",
  model_providers_not_configured: "未配置模型提供方存储",
};

const auth = useAuthStore();
const summary = ref<ModelSummary | null>(null);
const defaultModel = ref("");
const draftModel = ref("");
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("model.read"));
const canWrite = computed(() => auth.hasCapability("model.write"));

const providers = ref<ModelProvider[]>([]);
const keyEntry = ref(false);
const providerMessage = ref("");
const keyDrafts = ref<Record<string, string>>({});
const draft = ref({
  provider_id: "",
  kind: "litellm",
  model: "",
  base_url: "",
  secret_ref: "",
  enabled: true,
});

function aliasesLabel(aliases: string[] | undefined): string {
  return aliases && aliases.length ? aliases.join(", ") : "—";
}

async function failure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return PROVIDER_ERRORS[body.error ?? ""] ?? `保存失败: ${response.status}`;
  } catch {
    return `保存失败: ${response.status}`;
  }
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

async function loadProviders() {
  try {
    const body = await getJson<{ providers: ModelProvider[]; key_entry: boolean }>(
      "/api/model-providers",
    );
    providers.value = body.providers;
    keyEntry.value = body.key_entry;
    providerMessage.value = "";
  } catch {
    providerMessage.value = "未配置模型提供方存储（需要 --model-providers-dir）";
  }
}

function editProvider(provider: ModelProvider) {
  draft.value = {
    provider_id: provider.provider_id,
    kind: provider.kind,
    model: provider.model,
    base_url: provider.base_url ?? "",
    secret_ref: provider.secret_ref ?? "",
    enabled: provider.enabled,
  };
}

async function saveProvider() {
  const provider_id = draft.value.provider_id.trim();
  const model = draft.value.model.trim();
  if (!provider_id || !model) {
    providerMessage.value = "需要提供方 id 与模型";
    return;
  }
  const response = await apiFetch(
    `/api/model-providers/${encodeURIComponent(provider_id)}`,
    {
      method: "PUT",
      body: JSON.stringify({
        kind: draft.value.kind,
        model,
        base_url: draft.value.base_url.trim() || null,
        secret_ref: draft.value.secret_ref.trim() || null,
        enabled: draft.value.enabled,
      }),
    },
  );
  if (!response.ok) {
    providerMessage.value = await failure(response);
    return;
  }
  providerMessage.value = "已保存";
  await loadProviders();
}

async function saveKey(provider_id: string) {
  const value = (keyDrafts.value[provider_id] ?? "").trim();
  if (!value) {
    providerMessage.value = "需要密钥";
    return;
  }
  const response = await apiFetch(`/api/model-providers/${provider_id}/key`, {
    method: "PUT",
    body: JSON.stringify({ api_key: value }),
  });
  if (!response.ok) {
    providerMessage.value = await failure(response);
    return;
  }
  keyDrafts.value[provider_id] = "";
  providerMessage.value = "密钥已保存";
  await loadProviders();
}

async function revokeKey(provider_id: string) {
  const response = await apiFetch(`/api/model-providers/${provider_id}/key`, {
    method: "DELETE",
  });
  providerMessage.value = response.ok ? "密钥已吊销" : await failure(response);
  if (response.ok) await loadProviders();
}

onMounted(async () => {
  if (denied.value) return;
  try {
    summary.value = await getJson<ModelSummary>("/api/model");
  } catch {
    error.value = "model unavailable";
  }
  await loadDefaultModel();
  await loadProviders();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="模型" description="调用、别名、默认模型与提供方" />
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

      <h2>模型提供方</h2>
      <p v-if="providerMessage" class="login-msg">{{ providerMessage }}</p>
      <p v-if="providerMessage && !providers.length" class="placeholder">
        {{ providerMessage }}
      </p>
      <div v-if="providers.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>提供方</th>
              <th>类型</th>
              <th>模型</th>
              <th>端点</th>
              <th>密钥</th>
              <th>状态</th>
              <th v-if="canWrite">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="provider in providers" :key="provider.provider_id">
              <td>{{ provider.provider_id }}</td>
              <td>{{ provider.kind }}</td>
              <td>{{ provider.model }}</td>
              <td>{{ provider.base_url || "—" }}</td>
              <td class="key-cell">
                <span v-if="provider.key_configured">{{ provider.key_hint }}</span>
                <span v-else-if="provider.secret_ref">{{ provider.secret_ref }}</span>
                <span v-else>—</span>
                <template v-if="keyEntry && canWrite">
                  <div class="key-row">
                    <input
                      v-model="keyDrafts[provider.provider_id]"
                      type="password"
                      autocomplete="off"
                      placeholder="写入新密钥"
                    />
                    <button @click="saveKey(provider.provider_id)">保存密钥</button>
                    <button
                      v-if="provider.key_configured"
                      class="danger"
                      @click="revokeKey(provider.provider_id)"
                    >
                      吊销
                    </button>
                  </div>
                </template>
              </td>
              <td class="nowrap">{{ provider.enabled ? "启用" : "停用" }}</td>
              <td v-if="canWrite">
                <button @click="editProvider(provider)">编辑</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else-if="!providerMessage" class="placeholder">暂无提供方记录</p>

      <template v-if="canWrite">
        <div class="row">
          <input
            v-model="draft.provider_id"
            placeholder="provider_id，例如 deepseek-prod"
            autocomplete="off"
          />
          <select v-model="draft.kind">
            <option v-for="kind in KINDS" :key="kind" :value="kind">{{ kind }}</option>
          </select>
          <input
            v-model="draft.model"
            class="grow"
            placeholder="litellm:deepseek/deepseek-v4-pro"
            autocomplete="off"
          />
        </div>
        <div class="row">
          <input v-model="draft.base_url" class="grow" placeholder="base_url（可选）" />
          <input
            v-model="draft.secret_ref"
            class="grow"
            placeholder="secret://tenant/name（可选）"
            autocomplete="off"
          />
          <label><input v-model="draft.enabled" type="checkbox" /> 启用</label>
          <button class="primary" @click="saveProvider">保存提供方</button>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.key-cell {
  min-width: 260px;
}

.key-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.key-row input {
  max-width: 170px;
}

.nowrap {
  white-space: nowrap;
}
</style>
