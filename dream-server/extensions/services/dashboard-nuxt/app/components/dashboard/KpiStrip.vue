<!--
  KPI-Strip auf der Dashboard-Startseite. Zeigt die wichtigsten
  System-Metriken als Tile-Grid. Datenquelle: useSystemStore -> status.

  Das React-Pendant (Dashboard.jsx Zeile 555-685) baut die Liste
  imperativ ueber `systemMetrics.push(...)`. Wir bauen sie hier als
  computed property; die Komponenten-Logik bleibt deklarativ.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useSystemStore } from '~/stores/system'

interface MetricTile {
  icon: string
  label: string
  value: string
  subvalue?: string
  percent?: number
  alert?: boolean
}

const store = useSystemStore()
const { status } = storeToRefs(store)

function formatUptime(seconds = 0): string {
  if (!seconds) return '-'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

const metrics = computed<MetricTile[]>(() => {
  const s = status.value
  if (!s) return []
  const out: MetricTile[] = []
  const gpu = s.gpu
  const ram = s.ram
  const cpu = s.cpu
  const inf = s.inference

  if (gpu) {
    if (gpu.memoryType === 'unified') {
      // Apple Silicon / Halo Strix: GPU-Util ist nicht aussagekraeftig
      // (oft 0). Wir zeigen Chip + unified Memory.
      out.push({
        icon: 'i-lucide-zap',
        label: 'Chip',
        value: gpu.name.replace(/^(Apple|AMD|NVIDIA)\s+/, ''),
        subvalue: gpu.backend ?? 'unified',
      })
      if (ram) {
        out.push({
          icon: 'i-lucide-hard-drive',
          label: 'Mem Used',
          value: `${ram.used_gb.toFixed(1)} GB`,
          subvalue: `of ${ram.total_gb.toFixed(0)} GB unified`,
          percent: ram.percent,
        })
      }
    }
    else {
      out.push({
        icon: 'i-lucide-activity',
        label: 'GPU',
        value: `${gpu.utilization}%`,
        subvalue: gpu.name.replace(/^(NVIDIA|AMD)\s+/, ''),
        percent: gpu.utilization,
      })
      out.push({
        icon: 'i-lucide-hard-drive',
        label: 'VRAM',
        value: `${gpu.vramUsed.toFixed(1)} GB`,
        subvalue: `of ${gpu.vramTotal} GB`,
        percent: gpu.vramTotal > 0 ? (gpu.vramUsed / gpu.vramTotal) * 100 : 0,
      })
    }
  }

  if (cpu) {
    out.push({
      icon: 'i-lucide-cpu',
      label: 'CPU',
      value: `${cpu.percent.toFixed(1)}%`,
      subvalue: cpu.temp_c != null ? `${cpu.temp_c}°C` : 'utilization',
      percent: cpu.percent,
    })
  }

  if (ram && gpu?.memoryType !== 'unified') {
    out.push({
      icon: 'i-lucide-hard-drive',
      label: 'RAM',
      value: `${ram.used_gb.toFixed(1)} GB`,
      subvalue: `of ${ram.total_gb.toFixed(0)} GB`,
      percent: ram.percent,
    })
  }

  if (gpu?.powerDraw != null) {
    out.push({
      icon: 'i-lucide-power',
      label: 'GPU Power',
      value: `${gpu.powerDraw.toFixed(1)} W`,
      subvalue: 'live',
    })
  }

  if (gpu && gpu.memoryType !== 'unified') {
    const t = gpu.temperature
    out.push({
      icon: 'i-lucide-thermometer',
      label: 'GPU Temp',
      value: t != null ? `${t}°C` : '-',
      subvalue: t == null ? 'thermal' : t < 70 ? 'normal' : t < 85 ? 'warm' : 'hot',
      alert: (t ?? 0) >= 85,
    })
  }

  out.push({
    icon: 'i-lucide-brackets',
    label: 'Context',
    value: inf?.contextSize ? `${(inf.contextSize / 1024).toFixed(0)}k` : '-',
    subvalue: 'max tokens',
  })

  out.push({
    icon: 'i-lucide-clock',
    label: 'Uptime',
    value: formatUptime(s.uptime),
    subvalue: 'system',
  })

  out.push({
    icon: 'i-lucide-brain',
    label: 'Model',
    value: inf?.loadedModel ?? s.model?.name ?? '-',
    subvalue: 'loaded',
  })

  return out
})

function percentColor(p?: number): 'success' | 'warning' | 'error' {
  if (p == null) return 'success'
  if (p >= 90) return 'error'
  if (p >= 75) return 'warning'
  return 'success'
}
</script>

<template>
  <div class="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
    <UCard
      v-for="m in metrics"
      :key="m.label"
      :ui="{ root: m.alert ? 'ring-2 ring-error/40' : '' }"
    >
      <div class="flex items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted">
            <UIcon :name="m.icon" class="size-3.5" />
            {{ m.label }}
          </div>
          <p class="mt-1 truncate text-lg font-bold text-default" :title="m.value">
            {{ m.value }}
          </p>
          <p v-if="m.subvalue" class="truncate text-xs text-muted" :title="m.subvalue">
            {{ m.subvalue }}
          </p>
        </div>
      </div>
      <UProgress
        v-if="m.percent != null"
        class="mt-3"
        :model-value="Math.min(Math.max(m.percent, 0), 100)"
        :max="100"
        size="xs"
        :color="percentColor(m.percent)"
      />
    </UCard>
  </div>
</template>

