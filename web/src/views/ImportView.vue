<script setup lang="ts">
import { computed, ref } from "vue";
import { apiFetch } from "../api/client";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const kind = ref("terminology");
const payload = ref("");
const result = ref("");
const denied = computed(() => !auth.hasCapability("runs.read"));

async function runImport() {
  const raw = payload.value.trim();
  if (!raw) return;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    result.value = "invalid json";
    return;
  }
  const response = await apiFetch(`/api/import/${kind.value}`, {
    method: "POST",
    body: JSON.stringify(parsed),
  });
  const data = (await response.json()) as { error?: string };
  result.value = response.ok
    ? JSON.stringify(data)
    : `import failed (${response.status}): ${data.error ?? "error"}`;
}
</script>

<template>
  <div class="panel">
    <h1>导入</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <template v-else>
      <div class="row">
        <select v-model="kind">
          <option value="terminology">术语表</option>
          <option value="agent">Agent 定义</option>
        </select>
        <input
          v-model="payload"
          class="grow"
          placeholder="粘贴 JSON（ConceptScheme 或 manifest）"
          autocomplete="off"
        />
        <button class="primary" @click="runImport">Import</button>
      </div>
      <pre v-if="result" class="policy-view">{{ result }}</pre>
    </template>
  </div>
</template>
