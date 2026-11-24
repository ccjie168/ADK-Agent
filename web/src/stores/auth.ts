import { defineStore } from "pinia";
import { apiFetch, clearToken, getToken, setToken } from "../api/client";

const PKCE_VERIFIER_KEY = "adk_pkce_verifier";
const PKCE_STATE_KEY = "adk_pkce_state";

interface OidcConfig {
  enabled: boolean;
  client_id?: string;
  authorization_endpoint?: string;
  redirect_uri?: string;
  scopes?: string[];
}

interface Me {
  tenant: string;
  subject: string;
  roles: string[];
  capabilities: string[];
}

export const useAuthStore = defineStore("auth", {
  state: () => ({
    token: getToken(),
    oidc: { enabled: false } as OidcConfig,
    principal: null as Me | null,
    capabilities: [] as string[],
    loginError: "",
    ready: false,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
    hasCapability: (state) => (cap: string) => state.capabilities.includes(cap),
  },
  actions: {
    async loadConfig() {
      try {
        const response = await fetch("/auth/config");
        this.oidc = (await response.json()) as OidcConfig;
      } catch {
        this.oidc = { enabled: false };
      }
    },
    async fetchMe() {
      if (!this.token) return;
      const response = await apiFetch("/api/me");
      if (response.ok) {
        const me = (await response.json()) as Me;
        this.principal = me;
        this.capabilities = me.capabilities ?? [];
      }
    },
    async init() {
      try {
        await this.loadConfig();
        if (this.token) await this.fetchMe();
      } finally {
        this.ready = true;
      }
    },
    setTokenFromInput(token: string) {
      const trimmed = token.trim();
      if (!trimmed) return;
      setToken(trimmed);
      this.token = trimmed;
      return this.fetchMe().finally(() => {
        this.ready = true;
      });
    },
    async startLogin() {
      const oidc = this.oidc;
      if (!oidc.enabled || !oidc.authorization_endpoint) return;
      const verifier = randomString(48);
      const state = randomString(16);
      sessionStorage.setItem(PKCE_VERIFIER_KEY, verifier);
      sessionStorage.setItem(PKCE_STATE_KEY, state);
      const params = new URLSearchParams({
        response_type: "code",
        client_id: oidc.client_id ?? "",
        redirect_uri: oidc.redirect_uri ?? "",
        scope: (oidc.scopes ?? []).join(" "),
        state,
        code_challenge: await pkceChallenge(verifier),
        code_challenge_method: "S256",
      });
      const separator = oidc.authorization_endpoint.includes("?") ? "&" : "?";
      window.location.assign(oidc.authorization_endpoint + separator + params.toString());
    },
    async finishLogin(code: string, state: string): Promise<boolean> {
      const expected = sessionStorage.getItem(PKCE_STATE_KEY);
      const verifier = sessionStorage.getItem(PKCE_VERIFIER_KEY);
      sessionStorage.removeItem(PKCE_STATE_KEY);
      sessionStorage.removeItem(PKCE_VERIFIER_KEY);
      if (!code || !state || !expected || state !== expected || !verifier) {
        this.loginError = "登录状态不匹配，请重试";
        return false;
      }
      const response = await apiFetch("/auth/token", {
        method: "POST",
        body: JSON.stringify({
          code,
          code_verifier: verifier,
          redirect_uri: this.oidc.redirect_uri,
        }),
      });
      if (!response.ok) {
        this.loginError = `登录失败 (${response.status})`;
        return false;
      }
      const data = (await response.json()) as { access_token?: string };
      if (!data.access_token) {
        this.loginError = "登录响应缺少 access token";
        return false;
      }
      setToken(data.access_token);
      this.token = data.access_token;
      await this.fetchMe();
      this.ready = true;
      return true;
    },
    logout() {
      clearToken();
      this.token = "";
      this.principal = null;
      this.capabilities = [];
      this.ready = true;
    },
  },
});

function base64url(bytes: Uint8Array): string {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(size: number): string {
  const bytes = new Uint8Array(size);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function pkceChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}
