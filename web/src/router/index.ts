import { createRouter, createWebHashHistory } from "vue-router";
import AgentHubView from "../views/AgentHubView.vue";
import AgentWizardView from "../views/AgentWizardView.vue";
import ApprovalsView from "../views/ApprovalsView.vue";
import AskAiView from "../views/AskAiView.vue";
import AuditView from "../views/AuditView.vue";
import ChatView from "../views/ChatView.vue";
import ConnectorsView from "../views/ConnectorsView.vue";
import CredentialsView from "../views/CredentialsView.vue";
import EcosystemView from "../views/EcosystemView.vue";
import GrantsView from "../views/GrantsView.vue";
import ImportView from "../views/ImportView.vue";
import ModelView from "../views/ModelView.vue";
import OverviewView from "../views/OverviewView.vue";
import PeersView from "../views/PeersView.vue";
import PlaceholderView from "../views/PlaceholderView.vue";
import PlansView from "../views/PlansView.vue";
import PolicyView from "../views/PolicyView.vue";
import QuotaView from "../views/QuotaView.vue";
import RagView from "../views/RagView.vue";
import RegistryView from "../views/RegistryView.vue";
import RolesView from "../views/RolesView.vue";
import RunsView from "../views/RunsView.vue";
import SecurityView from "../views/SecurityView.vue";
import SemanticsView from "../views/SemanticsView.vue";
import SessionsView from "../views/SessionsView.vue";
import ToolsView from "../views/ToolsView.vue";
import UsersView from "../views/UsersView.vue";

const routes = [
  { path: "/", name: "home", component: OverviewView },
  { path: "/agents", name: "agents", component: AgentHubView },
  { path: "/agents/new", name: "agent-new", component: AgentWizardView },
  { path: "/approvals", name: "approvals", component: ApprovalsView },
  { path: "/ask-ai", name: "ask-ai", component: AskAiView },
  { path: "/chat", name: "chat", component: ChatView },
  { path: "/connectors", name: "connectors", component: ConnectorsView },
  { path: "/ecosystem", name: "ecosystem", component: EcosystemView },
  { path: "/credentials", name: "credentials", component: CredentialsView },
  { path: "/grants", name: "grants", component: GrantsView },
  { path: "/import", name: "import", component: ImportView },
  { path: "/peers", name: "peers", component: PeersView },
  { path: "/plans", name: "plans", component: PlansView },
  { path: "/policy", name: "policy", component: PolicyView },
  { path: "/registry", name: "registry", component: RegistryView },
  { path: "/audit", name: "audit", component: AuditView },
  { path: "/model", name: "model", component: ModelView },
  { path: "/roles", name: "roles", component: RolesView },
  { path: "/quota", name: "quota", component: QuotaView },
  { path: "/rag", name: "rag", component: RagView },
  { path: "/runs", name: "runs", component: RunsView },
  { path: "/security", name: "security", component: SecurityView },
  { path: "/semantics", name: "semantics", component: SemanticsView },
  { path: "/sessions", name: "sessions", component: SessionsView },
  { path: "/tools", name: "tools", component: ToolsView },
  { path: "/settings", name: "settings", component: PlaceholderView },
  { path: "/users", name: "users", component: UsersView },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});
