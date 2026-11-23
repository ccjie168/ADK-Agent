<script setup lang="ts">
import { useRoute } from "vue-router";

const route = useRoute();
</script>

<template>
  <div class="panel">
    <h1>{{ String(route.name ?? "面板") }}</h1>
    <p class="placeholder">此面板将在后续切片迁到 Vue。</p>
  </div>
</template>
