// One definition of the console navigation: the sidebar and the command
// palette both read it, so capability rules cannot drift apart.

export type NavItem = {
  to: string;
  label: string;
  icon: string;
  capabilities?: string[];
  external?: boolean;
};

export type NavSection = {
  label?: string;
  items: NavItem[];
};

export type NavGroup = {
  label: string;
  sections: NavSection[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "概览",
    sections: [
      {
        items: [
          { to: "/", label: "总览", icon: "home", capabilities: ["ops.read"] },
          { to: "/agents", label: "Agent", icon: "agent", capabilities: ["registry.read"] },
          { to: "/registry", label: "注册表", icon: "registry", capabilities: ["registry.read"] },
        ],
      },
    ],
  },
  {
    label: "运行",
    sections: [
      {
        items: [
          { to: "/runs", label: "运行", icon: "runs", capabilities: ["runs.read"] },
          { to: "/plans", label: "计划", icon: "plans", capabilities: ["runs.read"] },
          { to: "/sessions", label: "会话", icon: "sessions", capabilities: ["sessions.read"] },
          { to: "/approvals", label: "审批", icon: "approvals", capabilities: ["approvals.read"] },
          { to: "/chat", label: "聊天", icon: "chat", capabilities: ["chat.run"] },
          { to: "/ask-ai", label: "Ask AI", icon: "sparkles", capabilities: ["runs.read"] },
        ],
      },
    ],
  },
  {
    label: "治理",
    sections: [
      {
        label: "访问控制",
        items: [
          { to: "/policy", label: "策略", icon: "policy", capabilities: ["policy.read"] },
          { to: "/roles", label: "角色", icon: "roles", capabilities: ["roles.read"] },
          { to: "/users", label: "用户", icon: "users", capabilities: ["roles.read"] },
          { to: "/grants", label: "授权", icon: "grants", capabilities: ["grants.read"] },
        ],
      },
      {
        label: "审计与合规",
        items: [
          { to: "/audit", label: "审计", icon: "audit", capabilities: ["audit.read"] },
          { to: "/security", label: "安全", icon: "shield", capabilities: ["ops.read"] },
        ],
      },
      {
        label: "集成与配额",
        items: [
          { to: "/tools", label: "工具", icon: "tools", capabilities: ["tools.read"] },
          { to: "/connectors", label: "连接器", icon: "connectors", capabilities: ["connectors.read"] },
          { to: "/credentials", label: "凭据", icon: "credentials", capabilities: ["connectors.read"] },
          { to: "/peers", label: "对端", icon: "peers", capabilities: ["peers.read"] },
          { to: "/semantics", label: "语义层", icon: "semantics", capabilities: ["ops.read"] },
          { to: "/rag", label: "检索", icon: "rag", capabilities: ["ops.read"] },
          { to: "/quota", label: "配额", icon: "quota", capabilities: ["ops.read"] },
        ],
      },
    ],
  },
  {
    label: "开发",
    sections: [
      {
        items: [
          {
            to: "/agents/new",
            label: "新建 Agent",
            icon: "agent",
            capabilities: ["registry.publish", "registry.compose"],
          },
          { to: "/model", label: "模型", icon: "model", capabilities: ["model.read"] },
          {
            to: "/ecosystem",
            label: "生态",
            icon: "network",
            capabilities: ["tools.read", "connectors.read", "peers.read"],
          },
          { to: "/import", label: "导入", icon: "import", capabilities: ["runs.read"] },
        ],
      },
    ],
  },
  {
    label: "设置",
    sections: [
      {
        items: [
          { to: "/settings", label: "设置", icon: "settings" },
          { to: "/guide", label: "使用说明", icon: "policy", external: true },
        ],
      },
    ],
  },
];
