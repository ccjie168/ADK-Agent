import { createRouter, createWebHashHistory } from "vue-router";
import ApprovalsView from "../views/ApprovalsView.vue";
import AuditView from "../views/AuditView.vue";
import ConnectorsView from "../views/ConnectorsView.vue";
import CredentialsView from "../views/CredentialsView.vue";
import GrantsView from "../views/GrantsView.vue";
import ModelView from "../views/ModelView.vue";
import OverviewView from "../views/OverviewView.vue";
import PeersView from "../views/PeersView.vue";
import PlaceholderView from "../views/PlaceholderView.vue";
import PlansView from "../views/PlansView.vue";
import PolicyView from "../views/PolicyView.vue";
import QuotaView from "../views/QuotaView.vue";
import RagView from "../views/RagView.vue";
import RegistryView from "../views/RegistryView.vue";
import RunsView from "../views/RunsView.vue";
import SemanticsView from "../views/SemanticsView.vue";
import SessionsView from "../views/SessionsView.vue";
import ToolsView from "../views/ToolsView.vue";

const routes = [
  { path: "/", name: "home", component: OverviewView },
  { path: "/agents", name: "agents", component: PlaceholderView },
  { path: "/approvals", name: "approvals", component: ApprovalsView },
  { path: "/connectors", name: "connectors", component: ConnectorsView },
  { path: "/credentials", name: "credentials", component: CredentialsView },
  { path: "/grants", name: "grants", component: GrantsView },
  { path: "/peers", name: "peers", component: PeersView },
  { path: "/plans", name: "plans", component: PlansView },
  { path: "/policy", name: "policy", component: PolicyView },
  { path: "/registry", name: "registry", component: RegistryView },
  { path: "/audit", name: "audit", component: AuditView },
  { path: "/model", name: "model", component: ModelView },
  { path: "/quota", name: "quota", component: QuotaView },
  { path: "/rag", name: "rag", component: RagView },
  { path: "/runs", name: "runs", component: RunsView },
  { path: "/semantics", name: "semantics", component: SemanticsView },
  { path: "/sessions", name: "sessions", component: SessionsView },
  { path: "/tools", name: "tools", component: ToolsView },
  { path: "/settings", name: "settings", component: PlaceholderView },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});
