<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRouter } from "vue-router";
import NavIcon from "./NavIcon.vue";
import { NAV_GROUPS, type NavItem } from "../nav";
import { useAuthStore } from "../stores/auth";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const router = useRouter();
const auth = useAuthStore();
const query = ref("");
const active = ref(0);
const input = ref<HTMLInputElement | null>(null);
let returnFocus: HTMLElement | null = null;

const entries = computed<NavItem[]>(() => {
  const items: NavItem[] = [];
  for (const group of NAV_GROUPS) {
    for (const section of group.sections) {
      for (const item of section.items) {
        if (item.external) continue;
        if (item.capabilities && !item.capabilities.some((cap) => auth.hasCapability(cap))) {
          continue;
        }
        items.push(item);
      }
    }
  }
  return items;
});

const results = computed<NavItem[]>(() => {
  const needle = query.value.trim().toLowerCase();
  if (!needle) return entries.value;
  return entries.value.filter(
    (item) =>
      item.label.toLowerCase().includes(needle) || item.to.toLowerCase().includes(needle),
  );
});

watch(results, () => {
  active.value = 0;
});

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      returnFocus?.focus();
      returnFocus = null;
      return;
    }
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    query.value = "";
    active.value = 0;
    await nextTick();
    input.value?.focus();
  },
);

function move(delta: number) {
  const count = results.value.length;
  if (!count) return;
  active.value = (active.value + delta + count) % count;
}

function choose(index: number = active.value) {
  const item = results.value[index];
  if (!item) return;
  router.push(item.to);
  emit("close");
}

function onKey(event: KeyboardEvent) {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    move(1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    move(-1);
  } else if (event.key === "Enter") {
    event.preventDefault();
    choose();
  } else if (event.key === "Escape") {
    event.preventDefault();
    emit("close");
  } else if (event.key === "Tab") {
    event.preventDefault();
  }
}
</script>

<template>
  <div v-if="open" class="palette-scrim" @click.self="emit('close')">
    <div class="palette" role="dialog" aria-modal="true" aria-label="命令面板">
      <input
        ref="input"
        v-model="query"
        class="palette-input"
        type="text"
        placeholder="跳转到页面"
        aria-label="跳转到页面"
        aria-controls="palette-list"
        :aria-activedescendant="results.length ? `palette-item-${active}` : undefined"
        @keydown="onKey"
      />
      <ul id="palette-list" class="palette-list" role="listbox" aria-label="页面">
        <li
          v-for="(item, index) in results"
          :id="`palette-item-${index}`"
          :key="item.to"
          role="option"
          :aria-selected="index === active"
          :class="{ active: index === active }"
          @mousemove="active = index"
          @click="choose(index)"
        >
          <NavIcon :name="item.icon" />
          <span>{{ item.label }}</span>
          <span class="palette-path">{{ item.to }}</span>
        </li>
      </ul>
      <p v-if="!results.length" class="palette-empty">没有匹配的页面</p>
      <p class="palette-hint">↑ ↓ 选择 · Enter 跳转 · Esc 关闭</p>
    </div>
  </div>
</template>
