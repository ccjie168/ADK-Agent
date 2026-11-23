<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface RoleBinding {
  role: string;
  subjects: string[];
  capabilities: string[];
}

interface AccessPolicy {
  version: string;
  bindings: RoleBinding[];
}

const auth = useAuthStore();
const policy = ref<AccessPolicy | null>(null);
const draft = ref("");
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("policy.read"));
const canWrite = computed(() => auth.hasCapability("policy.write"));

function pretty(value: AccessPolicy | null): string {
  return value ? JSON.stringify(value, null, 2) : "";
}

function applyPolicy(value: AccessPolicy) {
  policy.value = value;
  draft.value = pretty(value);
}

async function save() {
  let parsed: AccessPolicy;
  try {
    parsed = JSON.parse(draft.value) as AccessPolicy;
  } catch {
    message.value = "JSON 格式无效";
    return;
  }
  let response: Response;
  try {
    response = await apiFetch("/api/policy", {
      method: "PUT",
      body: JSON.stringify(parsed),
    });
  } catch {
    message.value = "保存失败: 网络错误";
    return;
  }
  if (response.ok) {
    applyPolicy((await response.json()) as AccessPolicy);
    message.value = "已保存";
    return;
  }
  if (response.status === 400) message.value = "策略无效";
  else if (response.status === 403) message.value = "策略被拒绝";
  else message.value = `保存失败: ${response.status}`;
}

onMounted(async () => {
  if (denied.value) return;
  try {
    applyPolicy(await getJson<AccessPolicy>("/api/policy"));
  } catch {
    error.value = "policy unavailable";
  }
});
</script>

<template>
  <div class="panel">
    <h1>策略</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <template v-if="canWrite">
        <textarea v-model="draft" class="policy-editor" rows="18" spellcheck="false" />
        <div class="row">
          <button class="primary" @click="save">保存</button>
        </div>
      </template>
      <pre v-else-if="policy" class="policy-view">{{ pretty(policy) }}</pre>
      <p v-else class="placeholder">暂无策略</p>
    </template>
  </div>
</template>
