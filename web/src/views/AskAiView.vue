<script setup lang="ts">
import { computed, ref } from "vue";
import { apiFetch } from "../api/client";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

const auth = useAuthStore();
const text = ref("");
const result = ref("");
const denied = computed(() => !auth.hasCapability("runs.read"));

async function runAskAi() {
  if (!text.value.trim()) return;
  const response = await apiFetch("/api/ask-ai", {
    method: "POST",
    body: JSON.stringify({ text: text.value, bindings: [] }),
  });
  const data = (await response.json()) as { error?: string };
  result.value = response.ok
    ? JSON.stringify(data)
    : `ask failed (${response.status}): ${data.error ?? "error"}`;
}
</script>

<template>
  <div class="panel">
    <PageHeader title="Ask AI" description="用术语表做确定性路由回放" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <template v-else>
      <div class="row">
        <input
          v-model="text"
          class="grow"
          placeholder="用自然语言描述需求..."
          autocomplete="off"
        />
        <button class="primary" @click="runAskAi">Ask</button>
      </div>
      <pre v-if="result" class="policy-view">{{ result }}</pre>
    </template>
  </div>
</template>
