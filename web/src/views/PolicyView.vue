<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
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
const error = ref("");
const denied = computed(() => !auth.hasCapability("policy.read"));

function pretty(): string {
  return policy.value ? JSON.stringify(policy.value, null, 2) : "";
}

onMounted(async () => {
  if (denied.value) return;
  try {
    policy.value = await getJson<AccessPolicy>("/api/policy");
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
    <pre v-else-if="policy" class="policy-view">{{ pretty() }}</pre>
    <p v-else class="placeholder">暂无策略</p>
  </div>
</template>
