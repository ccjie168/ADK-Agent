<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterView } from "vue-router";
import NavIcon from "./components/NavIcon.vue";
import { router } from "./router";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const tokenInput = ref("");
const navOpen = ref(false);
const booting = computed(() => auth.isAuthenticated && !auth.ready);

function closeNav() {
  navOpen.value = false;
}

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
      <div class="topbar-left">
        <button
          v-if="auth.isAuthenticated"
          class="nav-toggle"
          aria-label="打开导航"
          @click="navOpen = !navOpen"
        >
          <NavIcon name="menu" />
        </button>
        <span class="brand"><span class="brand-mark">A</span>ADK Console</span>
      </div>
      <div class="topbar-right">
        <template v-if="auth.isAuthenticated">
          <span class="tenant-chip">{{ auth.principal?.tenant ?? "本地" }}</span>
          <span class="subject">{{ auth.principal?.subject }}</span>
          <button class="logout" @click="auth.logout()">退出</button>
        </template>
      </div>
    </header>

    <div v-if="auth.isAuthenticated" class="body">
      <div v-if="navOpen" class="nav-scrim" @click="closeNav"></div>
      <nav class="sidebar" :class="{ open: navOpen }">
        <div class="nav-group">
          <div class="nav-group-label">概览</div>
          <router-link to="/" class="nav-item" @click="closeNav">
            <NavIcon name="home" /><span>总览</span>
          </router-link>
          <router-link to="/agents" class="nav-item" @click="closeNav">
            <NavIcon name="agent" /><span>Agent</span>
          </router-link>
          <router-link to="/registry" class="nav-item" @click="closeNav">
            <NavIcon name="registry" /><span>注册表</span>
          </router-link>
        </div>
        <div class="nav-group">
          <div class="nav-group-label">运行</div>
          <router-link to="/runs" class="nav-item" @click="closeNav">
            <NavIcon name="runs" /><span>运行</span>
          </router-link>
          <router-link to="/plans" class="nav-item" @click="closeNav">
            <NavIcon name="plans" /><span>计划</span>
          </router-link>
          <router-link to="/sessions" class="nav-item" @click="closeNav">
            <NavIcon name="sessions" /><span>会话</span>
          </router-link>
          <router-link to="/approvals" class="nav-item" @click="closeNav">
            <NavIcon name="approvals" /><span>审批</span>
          </router-link>
          <router-link to="/chat" class="nav-item" @click="closeNav">
            <NavIcon name="chat" /><span>聊天</span>
          </router-link>
          <router-link to="/ask-ai" class="nav-item" @click="closeNav">
            <NavIcon name="sparkles" /><span>Ask AI</span>
          </router-link>
        </div>
        <div class="nav-group">
          <div class="nav-group-label">治理</div>
          <router-link to="/audit" class="nav-item" @click="closeNav">
            <NavIcon name="audit" /><span>审计</span>
          </router-link>
          <router-link to="/security" class="nav-item" @click="closeNav">
            <NavIcon name="shield" /><span>安全</span>
          </router-link>
          <router-link to="/policy" class="nav-item" @click="closeNav">
            <NavIcon name="policy" /><span>策略</span>
          </router-link>
          <router-link to="/roles" class="nav-item" @click="closeNav">
            <NavIcon name="roles" /><span>角色</span>
          </router-link>
          <router-link to="/users" class="nav-item" @click="closeNav">
            <NavIcon name="users" /><span>用户</span>
          </router-link>
          <router-link to="/tools" class="nav-item" @click="closeNav">
            <NavIcon name="tools" /><span>工具</span>
          </router-link>
          <router-link to="/grants" class="nav-item" @click="closeNav">
            <NavIcon name="grants" /><span>授权</span>
          </router-link>
          <router-link to="/connectors" class="nav-item" @click="closeNav">
            <NavIcon name="connectors" /><span>连接器</span>
          </router-link>
          <router-link to="/credentials" class="nav-item" @click="closeNav">
            <NavIcon name="credentials" /><span>凭据</span>
          </router-link>
          <router-link to="/peers" class="nav-item" @click="closeNav">
            <NavIcon name="peers" /><span>对端</span>
          </router-link>
          <router-link to="/semantics" class="nav-item" @click="closeNav">
            <NavIcon name="semantics" /><span>语义层</span>
          </router-link>
          <router-link to="/rag" class="nav-item" @click="closeNav">
            <NavIcon name="rag" /><span>检索</span>
          </router-link>
          <router-link to="/quota" class="nav-item" @click="closeNav">
            <NavIcon name="quota" /><span>配额</span>
          </router-link>
        </div>
        <div class="nav-group">
          <div class="nav-group-label">开发</div>
          <router-link to="/model" class="nav-item" @click="closeNav">
            <NavIcon name="model" /><span>模型</span>
          </router-link>
          <router-link to="/import" class="nav-item" @click="closeNav">
            <NavIcon name="import" /><span>导入</span>
          </router-link>
        </div>
        <div class="nav-group">
          <div class="nav-group-label">设置</div>
          <router-link to="/settings" class="nav-item" @click="closeNav">
            <NavIcon name="settings" /><span>设置</span>
          </router-link>
        </div>
      </nav>
      <main class="main">
        <div v-if="booting" class="boot">正在加载权限…</div>
        <RouterView v-else />
      </main>
    </div>

    <div v-else-if="auth.ready" class="login">
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
    <div v-else class="boot">正在加载…</div>
  </div>
</template>
