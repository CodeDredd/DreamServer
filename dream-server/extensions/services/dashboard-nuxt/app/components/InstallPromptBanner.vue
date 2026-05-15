<!--
  Smart PWA Install-Prompt — sichtbar wenn:
    * usePwaInstall().canInstall === true  (3+ Visits, nicht dismissed,
      Browser unterstuetzt beforeinstallprompt, nicht standalone)
    * ODER iOS-Safari (kein BeforeInstallPromptEvent verfuegbar, daher
      manuelle Anleitung)
-->
<script setup lang="ts">
import { computed } from 'vue'
import { usePwaInstall } from '~/composables/usePwaInstall'

const { canInstall, isStandalone, promptInstall, dismiss } = usePwaInstall()

const isIos = computed(() => {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent.toLowerCase()
  return /iphone|ipad|ipod/.test(ua) && !/(crios|fxios)/.test(ua)
})

const shouldShow = computed(() => {
  if (isStandalone.value) return false
  return canInstall.value || isIos.value
})

async function handleInstall() {
  await promptInstall()
}
</script>

<template>
  <div
    v-if="shouldShow"
    role="dialog"
    aria-label="Add Dream to your home screen"
    class="fixed bottom-4 left-4 right-4 z-40 rounded-xl border border-primary/40 bg-elevated p-4 shadow-2xl md:left-auto md:right-4 md:max-w-sm"
  >
    <div class="flex items-start gap-3">
      <div class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-primary">
        <UIcon name="i-lucide-smartphone" class="size-5" />
      </div>
      <div class="min-w-0 flex-1">
        <p class="mb-1 text-sm font-semibold text-default">
          Make Dream feel like an app
        </p>
        <p v-if="isIos" class="text-xs leading-relaxed text-muted">
          Tap
          <UIcon name="i-lucide-share" class="mx-0.5 inline size-3 align-text-bottom text-primary" />
          <strong class="text-default">Share</strong>, then
          <strong class="text-default">Add to Home Screen</strong>.
        </p>
        <p v-else class="text-xs leading-relaxed text-muted">
          Install Dream as an app on this device for one-tap access.
        </p>
      </div>
      <UButton
        icon="i-lucide-x"
        size="xs"
        color="neutral"
        variant="ghost"
        aria-label="Dismiss"
        @click="dismiss"
      />
    </div>
    <div v-if="!isIos" class="mt-3 flex items-center gap-2">
      <UButton
        block
        icon="i-lucide-plus"
        color="primary"
        variant="solid"
        @click="handleInstall"
      >
        Add to home screen
      </UButton>
      <UButton
        size="sm"
        color="neutral"
        variant="ghost"
        @click="dismiss"
      >
        Not now
      </UButton>
    </div>
  </div>
</template>

