<script setup lang="ts">
defineProps<{
  title?: string;
  description?: string;
  actionLabel?: string;
  actionTo?: string;
}>();
</script>

<template>
  <div class="empty-state">
    <p class="empty-title"><slot /></p>
    <p v-if="title" class="empty-heading">{{ title }}</p>
    <p v-if="description" class="empty-hint">{{ description }}</p>
    <RouterLink v-if="actionLabel && actionTo" class="secondary empty-action" :to="actionTo">
      {{ actionLabel }}
    </RouterLink>
    <slot name="actions" />
  </div>
</template>
