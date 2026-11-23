import { createRouter, createWebHashHistory } from "vue-router";
import ApprovalsView from "../views/ApprovalsView.vue";
import AuditView from "../views/AuditView.vue";
import GrantsView from "../views/GrantsView.vue";
import OverviewView from "../views/OverviewView.vue";
import PlaceholderView from "../views/PlaceholderView.vue";
import RegistryView from "../views/RegistryView.vue";
import ToolsView from "../views/ToolsView.vue";

const routes = [
  { path: "/", name: "home", component: OverviewView },
  { path: "/agents", name: "agents", component: PlaceholderView },
  { path: "/approvals", name: "approvals", component: ApprovalsView },
  { path: "/grants", name: "grants", component: GrantsView },
  { path: "/registry", name: "registry", component: RegistryView },
  { path: "/audit", name: "audit", component: AuditView },
  { path: "/model", name: "model", component: PlaceholderView },
  { path: "/tools", name: "tools", component: ToolsView },
  { path: "/settings", name: "settings", component: PlaceholderView },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});
