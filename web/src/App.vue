<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterView } from "vue-router";
import { router } from "./router";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const tokenInput = ref("");

async function submitToken() {
  await auth.setTokenFromInput(tokenInput.value);
  tokenInput.value = "";
}

async function handleCallback() {
  const params = new URLSearchParams(window.location.search);
  const ok = await auth.finishLogin(params.get("code") ?? "", params.get("state") ?? "");
  if (ok) {
    history.replaceState({}, "", "/");
    await router.replace("/");
  }
}

onMounted(async () => {
  await auth.init();
  if (window.location.pathname === "/auth/callback") {
    await handleCallback();
  }
});
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <span class="brand">ADK Console · Vue</span>
      <button v-if="auth.isAuthenticated" class="logout" @click="auth.logout()">退出</button>
    </header>

    <div v-if="auth.isAuthenticated" class="body">
      <nav class="sidebar">
        <router-link to="/">总览</router-link>
        <router-link to="/agents">Agent</router-link>
        <router-link to="/registry">注册表</router-link>
        <router-link to="/audit">审计</router-link>
        <router-link to="/model">模型</router-link>
        <router-link to="/tools">工具</router-link>
        <router-link to="/roles">角色</router-link>
        <router-link to="/users">用户</router-link>
        <router-link to="/settings">设置</router-link>
      </nav>
      <main class="main">
        <RouterView />
      </main>
    </div>

    <div v-else class="login">
      <h1>登录</h1>
      <button v-if="auth.oidc.enabled" class="primary" @click="auth.startLogin()">
        使用单点登录
      </button>
      <form v-if="!auth.oidc.enabled" class="token-form" @submit.prevent="submitToken">
        <input
          v-model="tokenInput"
          type="password"
          placeholder="Bearer token"
          aria-label="Bearer token"
        />
        <button type="submit" class="primary">使用 token 登录</button>
      </form>
      <p v-if="auth.loginError" class="login-msg">{{ auth.loginError }}</p>
    </div>
  </div>
</template>
