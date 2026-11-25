<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getJson } from "../api/client";
import { apiFetch } from "../api/client";
import { CAPABILITIES } from "../api/capabilities";
import { useAuthStore } from "../stores/auth";
import PageHeader from "../components/PageHeader.vue";

interface RoleEntry {
  name: string;
  capabilities: string[];
  builtin: boolean;
  description: string;
}

const auth = useAuthStore();
const roles = ref<RoleEntry[]>([]);
const selected = ref<RoleEntry | null>(null);
const draftName = ref("");
const draftDescription = ref("");
const draftCapabilities = ref<string[]>([]);
const message = ref("");
const denied = computed(() => !auth.hasCapability("roles.read"));
const canWrite = computed(() => auth.hasCapability("roles.manage"));

async function load() {
  try {
    roles.value = (await getJson<{ roles: RoleEntry[] }>("/api/roles")).roles;
  } catch {
    message.value = "role store unavailable";
  }
}

function edit(role: RoleEntry | null) {
  selected.value = role;
  draftName.value = role?.name ?? "";
  draftDescription.value = role?.description ?? "";
  draftCapabilities.value = [...(role?.capabilities ?? [])];
  message.value = "";
}

function toggle(capability: string) {
  const index = draftCapabilities.value.indexOf(capability);
  if (index >= 0) draftCapabilities.value.splice(index, 1);
  else draftCapabilities.value.push(capability);
}

async function save() {
  if (!draftName.value.trim()) {
    message.value = "需要角色名";
    return;
  }
  const response = await apiFetch(`/api/roles/${encodeURIComponent(draftName.value.trim())}`, {
    method: "PUT",
    body: JSON.stringify({
      capabilities: draftCapabilities.value,
      description: draftDescription.value,
    }),
  });
  if (!response.ok) {
    message.value = `保存失败: ${response.status}`;
    return;
  }
  message.value = "已保存";
  await load();
  edit(roles.value.find((role) => role.name === draftName.value.trim()) ?? null);
}

async function remove(role: RoleEntry) {
  const response = await apiFetch(`/api/roles/${encodeURIComponent(role.name)}`, {
    method: "DELETE",
  });
  message.value = response.ok ? "已删除" : `删除失败: ${response.status}`;
  await load();
  if (selected.value?.name === role.name) edit(null);
}

onMounted(async () => {
  if (denied.value) return;
  await load();
});
</script>

<template>
  <div class="panel">
    <PageHeader title="用户与角色" description="角色与能力定义" />
    <p v-if="denied" class="placeholder">无访问权限</p>
    <template v-else>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <div class="row">
        <button v-if="canWrite" class="primary" @click="edit(null)">新增角色</button>
      </div>
      <div class="table-wrap">
  <table>
        <thead>
          <tr>
            <th>角色</th>
            <th>能力数</th>
            <th>内置</th>
            <th>描述</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="role in roles" :key="role.name" @click="edit(role)">
            <td>{{ role.name }}</td>
            <td>{{ role.capabilities.length }}</td>
            <td>{{ role.builtin ? "是" : "否" }}</td>
            <td>{{ role.description }}</td>
            <td>
              <button
                v-if="canWrite && !role.builtin"
                class="link"
                @click.stop="remove(role)"
              >
                删除
              </button>
            </td>
          </tr>
          <tr v-if="roles.length === 0">
            <td colspan="5" class="placeholder">暂无角色</td>
          </tr>
        </tbody>
        </table>
      </div>

      <template v-if="canWrite">
        <h2>{{ selected ? `编辑 ${selected.name}` : "新增角色" }}</h2>
        <div class="row">
          <input
            v-model="draftName"
            class="grow"
            placeholder="角色名"
            :disabled="selected !== null"
            autocomplete="off"
          />
          <input v-model="draftDescription" class="grow" placeholder="描述" autocomplete="off" />
        </div>
        <div class="capability-grid">
          <label v-for="capability in CAPABILITIES" :key="capability">
            <input
              type="checkbox"
              :checked="draftCapabilities.includes(capability)"
              @change="toggle(capability)"
            />
            <span>{{ capability }}</span>
          </label>
        </div>
        <div class="row">
          <button class="primary" @click="save">保存</button>
        </div>
      </template>
    </template>
  </div>
</template>
