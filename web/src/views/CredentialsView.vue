<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface CredentialBinding {
  credential_id: string;
  tenant: string;
  secret_ref: string;
  description?: string;
  enabled: boolean;
}

const auth = useAuthStore();
const credentials = ref<CredentialBinding[]>([]);
const draft = ref({
  credential_id: "",
  tenant: "",
  secret_ref: "",
  description: "",
});
const message = ref("");
const error = ref("");
const denied = computed(() => !auth.hasCapability("connectors.read"));
const canManage = computed(() => auth.hasCapability("connectors.manage"));

async function reload() {
  try {
    credentials.value = await getJson<CredentialBinding[]>("/api/credentials");
  } catch {
    error.value = "credentials unavailable";
  }
}

async function register() {
  let response: Response;
  try {
    response = await apiFetch("/api/credentials", {
      method: "POST",
      body: JSON.stringify({
        credential_id: draft.value.credential_id.trim(),
        tenant: draft.value.tenant.trim(),
        secret_ref: draft.value.secret_ref.trim(),
        description: draft.value.description.trim(),
      }),
    });
  } catch {
    message.value = "注册失败: 网络错误";
    return;
  }
  if (response.ok) {
    message.value = `已注册 ${draft.value.credential_id.trim()}`;
    await reload();
    return;
  }
  const codes: Record<string, string> = {
    invalid_credential: "凭据定义无效（secret_ref 须为 secret://租户/名称）",
    credential_conflict: "同名凭据已存在且定义不同",
  };
  message.value = `注册失败: ${codes[await errorCode(response)] ?? response.status}`;
}

async function errorCode(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: string };
    return body.error ?? "";
  } catch {
    return "";
  }
}

async function disable(binding: CredentialBinding) {
  let response: Response;
  try {
    response = await apiFetch(
      `/api/credentials/${encodeURIComponent(binding.credential_id)}/disable?tenant=${encodeURIComponent(binding.tenant)}`,
      { method: "POST" },
    );
  } catch {
    message.value = "禁用失败: 网络错误";
    return;
  }
  message.value = response.ok
    ? `已禁用 ${binding.credential_id}`
    : `禁用失败: ${response.status}`;
  await reload();
}

onMounted(async () => {
  if (denied.value) return;
  await reload();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="凭据" description="租户凭据引用与状态" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <p v-else-if="error" class="login-msg">{{ error }}</p>
    <template v-else>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <div class="table-wrap">
  <table class="data-table">
        <thead>
          <tr>
            <th>凭据 ID</th>
            <th>租户</th>
            <th>Secret 引用</th>
            <th>描述</th>
            <th>启用</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="binding in credentials" :key="binding.credential_id">
            <td>{{ binding.credential_id }}</td>
            <td>{{ binding.tenant }}</td>
            <td>{{ binding.secret_ref }}</td>
            <td>{{ binding.description ?? "" }}</td>
            <td>{{ binding.enabled ? "enabled" : "disabled" }}</td>
            <td>
              <button v-if="canManage && binding.enabled" class="link" @click="disable(binding)">
                禁用
              </button>
            </td>
          </tr>
          <tr v-if="credentials.length === 0">
            <td colspan="6" class="placeholder">暂无凭据</td>
          </tr>
        </tbody>
        </table>
      </div>

      <template v-if="canManage">
        <h2>注册凭据引用</h2>
        <p class="placeholder">页面只登记引用；密钥值仍由服务端环境变量提供，不经过浏览器。</p>
        <div class="row">
          <input v-model="draft.credential_id" class="grow" placeholder="凭据 ID" />
          <input v-model="draft.tenant" class="grow" placeholder="租户" />
        </div>
        <div class="row">
          <input
            v-model="draft.secret_ref"
            class="grow"
            placeholder="secret://租户/名称"
          />
          <input v-model="draft.description" class="grow" placeholder="描述" />
        </div>
        <div class="row">
          <button class="primary" @click="register">注册</button>
        </div>
      </template>
    </template>
  </div>
</template>
