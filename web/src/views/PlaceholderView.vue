<script setup lang="ts">
import { useRoute } from "vue-router";
import PageHeader from "../components/PageHeader.vue";

const route = useRoute();
</script>

<template>
  <div class="panel">
    <PageHeader :title="String(route.name ?? '面板')" />
    <p class="placeholder">此面板将在后续切片迁到 Vue。</p>
  </div>
</template>
