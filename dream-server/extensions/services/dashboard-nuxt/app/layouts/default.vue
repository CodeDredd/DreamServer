<script setup lang="ts">
// Phase 3 — App-Shell. Sidebar links, Hauptbereich rechts mit
// optionalem BootstrapBanner darueber. SystemStatus-/Version-Polling
// wird hier (statt in jeder Page) einmal angestossen.

import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'
import { useSystemStatus } from '~/composables/useSystemStatus'
import { useVersion } from '~/composables/useVersion'

useSystemStatus()
useVersion()

const systemStore = useSystemStore()
const { status } = storeToRefs(systemStore)
const bootstrap = computed(() => status.value?.bootstrap)
const showBootstrap = computed(() => Boolean(bootstrap.value?.active))
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-default text-default">
    <AppSidebar />
    <main class="flex flex-1 flex-col overflow-hidden">
      <BootstrapBanner v-if="showBootstrap && bootstrap" :bootstrap="bootstrap" />
      <div class="flex-1 overflow-y-auto">
        <slot />
      </div>
    </main>
  </div>
</template>

