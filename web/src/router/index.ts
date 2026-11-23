import { createRouter, createWebHashHistory } from "vue-router";
import PlaceholderView from "../views/PlaceholderView.vue";

const routes = [
  { path: "/", name: "home", component: PlaceholderView },
  { path: "/agents", name: "agents", component: PlaceholderView },
  { path: "/registry", name: "registry", component: PlaceholderView },
  { path: "/audit", name: "audit", component: PlaceholderView },
  { path: "/model", name: "model", component: PlaceholderView },
  { path: "/tools", name: "tools", component: PlaceholderView },
  { path: "/settings", name: "settings", component: PlaceholderView },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});
