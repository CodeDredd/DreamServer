<!--
  Feature-Discovery-Cards. React-Pendant: Dashboard.jsx Zeile 712-770
  + FeatureCard memo (779). Status-Logik aus normalizeFeatureStatus +
  pickFeatureLink (Zeile 51-83) ist hier zentralisiert.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useFeatures } from '~/composables/useFeatures'
import { useSystemStore } from '~/stores/system'
import type { FeatureItem } from '~/types/api'

const { features } = useFeatures()
const store = useSystemStore()
const { status } = storeToRefs(store)

// React-Icons (Lucide-Pascal) -> Iconify-Strings.
const ICON_MAP: Record<string, string> = {
  Globe: 'i-lucide-globe',
  MessageSquare: 'i-lucide-message-square',
  Mic: 'i-lucide-mic',
  FileText: 'i-lucide-file-text',
  Workflow: 'i-lucide-workflow',
  Image: 'i-lucide-image',
  Code: 'i-lucide-code',
  Bot: 'i-lucide-bot',
  Network: 'i-lucide-network',
  Search: 'i-lucide-search',
  Terminal: 'i-lucide-terminal',
}

function externalUrl(port: number): string {
  if (typeof window !== 'undefined') {
    return `http://${window.location.hostname}:${port}`
  }
  return `http://localhost:${port}`
}

function pickLink(feature: FeatureItem): string | null {
  const services = status.value?.services ?? []
  const req = feature.requirements ?? {}
  const wanted = [...(req.servicesAll ?? req.services ?? []), ...(req.servicesAny ?? [])]
  const match = (needle: string) =>
    services.find(s =>
      s.status === 'healthy' && s.port
      && (s.name ?? '').toLowerCase().includes(needle.toLowerCase()),
    )
  const first = wanted.map(match).find(Boolean)
  if (first?.port) return externalUrl(first.port)
  const fallback = match('webui') ?? match('open webui')
  return fallback?.port ? externalUrl(fallback.port) : null
}

interface FeatureCardData {
  id: string
  name: string
  description: string
  icon: string
  href: string | null
  ready: boolean
  hint: string | null
  setupTime?: string
}

const cards = computed<FeatureCardData[]>(() =>
  features.value.map((f) => {
    const ready = f.status === 'enabled' || f.status === 'available'
    const hint = !ready
      ? f.status === 'services_needed'
        ? `Benötigt: ${(f.requirements?.servicesMissing ?? []).join(', ')}`
        : f.status === 'insufficient_vram'
          ? `Benötigt ${f.requirements?.vramGb ?? 0} GB VRAM`
          : 'Nicht verfügbar'
      : null
    return {
      id: f.id,
      name: f.name,
      description: f.description,
      icon: ICON_MAP[f.icon ?? ''] ?? 'i-lucide-sparkles',
      href: pickLink(f),
      ready,
      hint,
      setupTime: f.setupTime,
    }
  }),
)
</script>

<template>
  <div v-if="cards.length" class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
    <UPageCard
      v-for="card in cards"
      :key="card.id"
      :title="card.name"
      :description="card.description"
      :icon="card.icon"
      :to="card.href ?? undefined"
      :target="card.href ? '_blank' : undefined"
      variant="subtle"
      :ui="{ root: !card.ready ? 'opacity-60' : '' }"
    >
      <template #footer>
        <div class="flex w-full items-center justify-between text-xs">
          <UBadge
            :color="card.ready ? 'success' : 'neutral'"
            variant="subtle"
            :icon="card.ready ? 'i-lucide-check-circle' : 'i-lucide-circle-dashed'"
            size="sm"
          >
            {{ card.ready ? 'Ready' : (card.setupTime ?? 'Setup') }}
          </UBadge>
          <UIcon
            v-if="card.href"
            name="i-lucide-external-link"
            class="size-3.5 text-muted"
          />
        </div>
        <p
          v-if="card.hint"
          class="mt-2 text-[11px] leading-snug text-muted"
        >
          {{ card.hint }}
        </p>
      </template>
    </UPageCard>
  </div>
</template>

