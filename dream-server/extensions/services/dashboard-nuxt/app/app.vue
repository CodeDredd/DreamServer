<script setup lang="ts">
// Wurzelkomponente. Splash + InstallPromptBanner liegen ueber dem
// Layout/Pages-Stack, damit sie auch FirstBoot/Wizard-Routen nicht
// blockieren (Phase 4 Welle D).

import { storeToRefs } from 'pinia'
import { useUiStore } from '~/stores/ui'

const ui = useUiStore()
const { splashShown } = storeToRefs(ui)

function handleSplashComplete() {
  ui.markSplashShown()
}
</script>

<template>
  <UApp>
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
    <ClientOnly>
      <AppSplash v-if="!splashShown" @complete="handleSplashComplete" />
      <InstallPromptBanner />
    </ClientOnly>
  </UApp>
</template>

