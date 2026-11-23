<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { apiFetch, getJson } from "../api/client";
import { useAuthStore } from "../stores/auth";

interface UserEntry {
  tenant: string;
  subject: string;
  roles: string[];
}

interface RoleEntry {
  name: string;
}

const auth = useAuthStore();
const users = ref<UserEntry[]>([]);
const roleNames = ref<string[]>([]);
const draftSubject = ref("");
const draftRoles = ref<string[]>([]);
const message = ref("");
const denied = computed(() => !auth.hasCapability("roles.read"));
const canWrite = computed(() => auth.hasCapability("roles.manage"));

async function load() {
  try {
    users.value = (await getJson<{ users: UserEntry[] }>("/api/users")).users;
  } catch {
    message.value = "user binding store unavailable";
  }
  try {
    roleNames.value = (await getJson<{ roles: RoleEntry[] }>("/api/roles")).roles.map(
      (role) => role.name,
    );
  } catch {
    roleNames.value = [];
  }
}

function edit(user: UserEntry | null) {
  draftSubject.value = user?.subject ?? "";
  draftRoles.value = [...(user?.roles ?? [])];
  message.value = "";
}

function toggle(name: string) {
  const index = draftRoles.value.indexOf(name);
  if (index >= 0) draftRoles.value.splice(index, 1);
  else draftRoles.value.push(name);
}

async function save() {
  const subject = draftSubject.value.trim();
  if (!subject) {
    message.value = "需要主体";
    return;
  }
  const response = await apiFetch(`/api/users/${encodeURIComponent(subject)}`, {
    method: "PUT",
    body: JSON.stringify({ roles: draftRoles.value }),
  });
  message.value = response.ok ? "已保存" : `保存失败: ${response.status}`;
  await load();
}

async function remove(user: UserEntry) {
  const response = await apiFetch(`/api/users/${encodeURIComponent(user.subject)}`, {
    method: "DELETE",
  });
  message.value = response.ok ? "已解绑" : `解绑失败: ${response.status}`;
  await load();
}

onMounted(async () => {
  if (denied.value) return;
  await load();
});
</script>

<template>
  <div class="panel">
    <h1>用户绑定</h1>
    <p v-if="denied" class="placeholder">无访问权限</p>
    <template v-else>
      <p v-if="message" class="login-msg">{{ message }}</p>
      <table>
        <thead>
          <tr>
            <th>租户</th>
            <th>主体</th>
            <th>角色</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.tenant + ':' + user.subject" @click="edit(user)">
            <td>{{ user.tenant }}</td>
            <td>{{ user.subject }}</td>
            <td>{{ user.roles.join(", ") }}</td>
            <td>
              <button v-if="canWrite" class="link" @click.stop="remove(user)">解绑</button>
            </td>
          </tr>
          <tr v-if="users.length === 0">
            <td colspan="4" class="placeholder">暂无绑定</td>
          </tr>
        </tbody>
      </table>

      <template v-if="canWrite">
        <h2>绑定或改绑</h2>
        <div class="row">
          <input v-model="draftSubject" class="grow" placeholder="主体" autocomplete="off" />
        </div>
        <div class="capability-grid">
          <label v-for="name in roleNames" :key="name">
            <input
              type="checkbox"
              :checked="draftRoles.includes(name)"
              @change="toggle(name)"
            />
            <span>{{ name }}</span>
          </label>
        </div>
        <div class="row">
          <button class="primary" @click="save">保存</button>
        </div>
      </template>
    </template>
  </div>
</template>
