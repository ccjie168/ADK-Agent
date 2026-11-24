<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{ name: string }>();

const PATHS: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z",
  agent:
    "M12 2v3M5 9h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zM9 14h.01M15 14h.01",
  registry: "M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8",
  runs: "M6 4l14 8-14 8z",
  plans: "M4 6h6M4 12h6M4 18h6M14 7l6 5-6 5",
  sessions: "M3 5h18v11H8l-5 4z",
  approvals:
    "M9 3h6a2 2 0 0 1 2 2v1h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2V5a2 2 0 0 1 2-2zM9 13l2 2 4-4",
  chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  sparkles:
    "M12 3l1.8 4.8L19 10l-5.2 2.2L12 17l-1.8-4.8L5 10l5.2-2.2zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z",
  audit: "M4 4h16v16H4zM8 8h8M8 12h8M8 16h5",
  shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  policy: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h5",
  roles:
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  users: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1",
  tools: "M14.5 6.5a4 4 0 0 0 5 5L9 22l-3-3zM6 6l3 3",
  grants: "M7.5 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM10.5 12H21M17 12v3M20 12v2",
  connectors: "M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5",
  credentials: "M4 10h16v11H4zM8 10V7a4 4 0 0 1 8 0v3M12 14v3",
  peers: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18",
  semantics: "M12 2 2 7l10 5 10-5zM2 12l10 5 10-5M2 17l10 5 10-5",
  rag: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM16.5 16.5 21 21",
  quota: "M22 12h-4l-3 9L9 3l-3 9H2",
  model: "M4 4h16v16H4zM9 9h6v6H9zM9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3",
  import: "M12 4v12M7 9l5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3",
  settings: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  menu: "M4 6h16M4 12h16M4 18h16",
  network:
    "M12 5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM5 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM19 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 5v6M5 17v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2",
};

const path = computed(() => PATHS[props.name] ?? PATHS.home);
</script>

<template>
  <svg
    class="nav-icon"
    viewBox="0 0 24 24"
    width="16"
    height="16"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path :d="path" />
  </svg>
</template>
