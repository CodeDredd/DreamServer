<!--
  Sidebar-Logo. Klein/kollabiert zeigt nur das Icon, expandiert das
  Wortlogo + Tier-Badge. Tier kommt aus dem System-Store.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'

defineProps<{
  collapsed?: boolean
}>()

const store = useSystemStore()
const { status } = storeToRefs(store)

const tier = computed(() => status.value?.tier ?? null)
</script>

<template>
  <NuxtLink
    to="/"
    class="flex items-center gap-2 px-1.5 py-1 text-default transition-colors hover:text-primary"
  >
    <span class="grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
      <UIcon name="i-lucide-cloud-lightning" class="size-5" />
    </span>
    <span v-if="!collapsed" class="flex flex-col leading-tight">
      <span class="text-sm font-semibold tracking-tight">DreamServer</span>
      <span v-if="tier" class="text-[10px] uppercase tracking-widest text-muted">
        {{ tier }}
      </span>
    </span>
  </NuxtLink>
</template>

