<!--
  GSAP-Splash 1:1 portiert aus dashboard/src/components/SplashScreen.jsx.
  - Vue-Reactivity bleibt aussen vor (markRaw via gsap.context).
  - Spielt einmal pro Browser-Session (Storage-Key 'dream-splash-shown'
    wird vom uiStore gesetzt; siehe app.vue).
  - Respektiert prefers-reduced-motion und Lo-End-Devices (deviceMemory,
    hardwareConcurrency, NetworkInformation.saveData).
  - ESC oder Klick = skip.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { gsap } from 'gsap'
import { useEventListener, useMediaQuery } from '@vueuse/core'

const emit = defineEmits<{ complete: [] }>()

const SPLASH_DURATION_MS = 2800
const EXIT_PAUSE_MS = 300
const FADE_DURATION_MS = 600
const LOW_END_ELLIPSE_COUNT = 14
const STANDARD_ELLIPSE_COUNT = 22

const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')

function isLowPerformanceDevice(): boolean {
  if (typeof navigator === 'undefined') return false
  const nav = navigator as Navigator & {
    deviceMemory?: number
    connection?: { saveData?: boolean }
  }
  const memory = typeof nav.deviceMemory === 'number' ? nav.deviceMemory : Infinity
  const cores = typeof nav.hardwareConcurrency === 'number' ? nav.hardwareConcurrency : Infinity
  return Boolean(nav.connection?.saveData) || memory <= 4 || cores <= 4
}

const lowPerformance = ref<boolean>(false)
const ellipseCount = computed(() =>
  lowPerformance.value ? LOW_END_ELLIPSE_COUNT : STANDARD_ELLIPSE_COUNT,
)

const svgRef = ref<SVGSVGElement | null>(null)
const progress = ref(0)
const glitching = ref(false)
const done = ref(false)
const completionGuard = ref(false)
const rafId = ref<number | null>(null)
const timeouts = ref<number[]>([])
let gsapCtx: ReturnType<typeof gsap.context> | null = null
let glitchTimer: number | null = null

function clearAll() {
  if (rafId.value !== null) {
    cancelAnimationFrame(rafId.value)
    rafId.value = null
  }
  for (const t of timeouts.value) {
    clearTimeout(t)
  }
  timeouts.value = []
  if (glitchTimer !== null) {
    clearTimeout(glitchTimer)
    glitchTimer = null
  }
  if (gsapCtx) {
    gsapCtx.revert()
    gsapCtx = null
  }
}

function finish(delay = FADE_DURATION_MS) {
  if (completionGuard.value) return
  completionGuard.value = true
  clearAll()
  glitching.value = false
  progress.value = 100
  done.value = true
  if (delay <= 0) {
    emit('complete')
    return
  }
  const t = window.setTimeout(() => emit('complete'), delay)
  timeouts.value.push(t)
}

function startOrbAnimation() {
  if (!svgRef.value || reducedMotion.value) return
  const svg = svgRef.value
  const ellipses = Array.from(svg.querySelectorAll('.ell')) as SVGEllipseElement[]
  const colors = ['#f72585', '#7209b7', '#3a0ca3', '#4361ee', '#4cc9f0', '#D9F4FC']
  const rxFactor = lowPerformance.value ? 2.4 : 3.2
  const ryFactor = lowPerformance.value ? 1.5 : 2
  const strokeStart = lowPerformance.value ? 8 : 10
  const strokeEnd = lowPerformance.value ? 56 : 84
  const colorInterp = gsap.utils.interpolate(colors)

  gsapCtx = gsap.context(() => {
    gsap.set(svg, { visibility: 'visible' })
    ellipses.forEach((el, i) => {
      const offset = i + 1
      const tl = gsap.timeline({
        defaults: { duration: lowPerformance.value ? 1.25 : 1, ease: 'sine.inOut' },
        repeat: -1,
      })
      gsap.set(el, {
        opacity: 1 - offset / ellipses.length,
        stroke: colorInterp(offset / ellipses.length),
      })
      tl.to(el, {
        attr: { rx: `+=${offset * rxFactor}`, ry: `-=${offset * ryFactor}` },
        strokeWidth: strokeStart,
        ease: 'power2.in',
      })
        .to(el, {
          strokeWidth: strokeEnd,
          attr: { rx: `-=${offset * rxFactor}`, ry: `+=${offset * ryFactor}` },
          ease: 'power2.out',
        })
        .to(el, {
          duration: lowPerformance.value ? 2.5 : 2,
          rotation: -360,
          transformOrigin: '50% 50%',
          ease: 'none',
        }, 0)
        .from(el, {
          duration: lowPerformance.value ? 1.1 : 0.9,
          scale: 0,
          transformOrigin: '50% 50%',
          ease: 'power2.out',
        }, 0)
        .timeScale(lowPerformance.value ? 0.42 : 0.54)
      tl.progress((offset / ellipses.length) * 0.35)
    })
  }, svg)
}

function startProgress() {
  if (reducedMotion.value) {
    finish(0)
    return
  }
  const start = performance.now()
  const tick = (now: number) => {
    const elapsed = now - start
    const p = Math.min(elapsed / SPLASH_DURATION_MS, 1)
    const eased = 1 - Math.pow(1 - p, 3)
    progress.value = Math.floor(eased * 100)
    if (p < 1) {
      rafId.value = requestAnimationFrame(tick)
    }
    else {
      progress.value = 100
      const t = window.setTimeout(() => finish(), EXIT_PAUSE_MS)
      timeouts.value.push(t)
    }
  }
  rafId.value = requestAnimationFrame(tick)
}

function scheduleGlitch() {
  if (reducedMotion.value) return
  glitchTimer = window.setTimeout(() => {
    glitching.value = true
    const off = window.setTimeout(() => {
      glitching.value = false
      scheduleGlitch()
    }, 80 + Math.random() * 120)
    timeouts.value.push(off)
  }, Math.random() * 900 + 200)
}

const glitchChars = '!@#$%^&*░▒▓█▄▀■□▪'
const title = 'DreamServer'
const displayTitle = computed(() =>
  glitching.value
    ? title
        .split('')
        .map(ch =>
          Math.random() < 0.18 ? glitchChars[Math.floor(Math.random() * glitchChars.length)] : ch,
        )
        .join('')
    : title,
)

useEventListener(typeof window !== 'undefined' ? window : null, 'keydown', (e: KeyboardEvent) => {
  if (e.key === 'Escape') finish(300)
})

onMounted(() => {
  lowPerformance.value = isLowPerformanceDevice()
  if (reducedMotion.value) {
    finish(0)
    return
  }
  startOrbAnimation()
  startProgress()
  scheduleGlitch()
})

onBeforeUnmount(() => {
  clearAll()
})

function skipClick() {
  finish(300)
}
</script>

<template>
  <div
    v-if="!reducedMotion"
    role="dialog"
    aria-modal="true"
    aria-labelledby="dream-splash-title"
    aria-describedby="dream-splash-status dream-splash-hint"
    :style="{
      position: 'fixed',
      inset: 0,
      zIndex: 9999,
      background: '#000',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      overflow: 'hidden',
      opacity: done ? 0 : 1,
      transition: done ? 'opacity 0.6s ease' : 'none',
      pointerEvents: done ? 'none' : 'all',
      cursor: 'pointer',
    }"
    @click="skipClick"
  >
    <!-- Decorative orb -->
    <div :style="{ position: 'absolute', inset: 0, opacity: 0.75 }" aria-hidden="true">
      <svg
        ref="svgRef"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 800 600"
        :style="{ width: '100%', height: '100%', visibility: 'hidden', position: 'absolute', inset: 0 }"
      >
        <ellipse
          v-for="i in ellipseCount"
          :key="i"
          class="ell"
          cx="400"
          cy="300"
          rx="180"
          ry="180"
          fill="none"
          :style="{ strokeWidth: 0, strokeLinecap: 'round', strokeLinejoin: 'round' }"
        />
      </svg>
    </div>

    <div
      :style="{
        position: 'relative',
        zIndex: 2,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '2rem',
        width: '100%',
        maxWidth: '520px',
        padding: '0 2rem',
      }"
    >
      <p
        id="dream-splash-status"
        role="status"
        aria-live="polite"
        aria-atomic="true"
        :aria-busy="!done"
        class="sr-only"
      >
        {{ done ? 'DreamServer is ready.' : `Loading DreamServer. ${progress}% complete.` }}
      </p>

      <h1 id="dream-splash-title" :style="{ position: 'relative', userSelect: 'none', margin: 0 }">
        <span class="sr-only">DreamServer</span>
        <span
          v-if="glitching"
          aria-hidden="true"
          :style="{
            position: 'absolute',
            top: 0,
            left: '2px',
            color: '#f72585',
            fontFamily: 'JetBrains Mono, Courier New, monospace',
            fontSize: 'clamp(2rem,6vw,3.5rem)',
            fontWeight: 900,
            letterSpacing: '0.05em',
            clipPath: 'polygon(0 20%,100% 20%,100% 45%,0 45%)',
            opacity: 0.9,
          }"
        >
          {{ displayTitle }}
        </span>
        <span
          v-if="glitching"
          aria-hidden="true"
          :style="{
            position: 'absolute',
            top: 0,
            left: '-3px',
            color: '#4cc9f0',
            fontFamily: 'JetBrains Mono, Courier New, monospace',
            fontSize: 'clamp(2rem,6vw,3.5rem)',
            fontWeight: 900,
            letterSpacing: '0.05em',
            clipPath: 'polygon(0 60%,100% 60%,100% 80%,0 80%)',
            opacity: 0.85,
          }"
        >
          {{ displayTitle }}
        </span>
        <span
          aria-hidden="true"
          :style="{
            fontFamily: 'JetBrains Mono, Courier New, monospace',
            fontSize: 'clamp(2rem,6vw,3.5rem)',
            fontWeight: 900,
            letterSpacing: '0.05em',
            background: 'linear-gradient(135deg,#e4e4e7 0%,#a78bfa 50%,#4cc9f0 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
            display: 'inline-block',
            filter: glitching ? 'blur(0.5px)' : 'none',
            transition: 'filter 0.05s',
          }"
        >
          {{ displayTitle }}
        </span>
      </h1>

      <p
        :style="{
          color: '#71717a',
          fontSize: '0.85rem',
          letterSpacing: '0.2em',
          textTransform: 'uppercase',
          fontFamily: 'JetBrains Mono, Courier New, monospace',
          margin: '-1.2rem 0 0',
        }"
      >
        Local AI Platform
      </p>

      <div :style="{ width: '100%' }" aria-hidden="true">
        <div :style="{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }">
          <span :style="{ color: '#52525b', fontSize: '0.7rem', letterSpacing: '0.15em', textTransform: 'uppercase', fontFamily: 'monospace' }">Initializing</span>
          <span
            :style="{
              fontFamily: 'JetBrains Mono, monospace',
              fontSize: '0.8rem',
              fontWeight: 700,
              color: progress === 100 ? '#4cc9f0' : '#a78bfa',
              transition: 'color 0.3s',
            }"
          >{{ progress }}%</span>
        </div>
        <div :style="{ width: '100%', height: '3px', background: '#27272a', borderRadius: '999px', overflow: 'hidden', position: 'relative' }">
          <div
            :style="{
              position: 'absolute',
              left: 0,
              top: 0,
              height: '100%',
              width: `${progress}%`,
              background: 'linear-gradient(90deg,#7209b7,#4361ee,#4cc9f0)',
              borderRadius: '999px',
              transition: 'width 0.1s linear',
              boxShadow: '0 0 12px #4cc9f090',
            }"
          />
        </div>
      </div>

      <button
        type="button"
        aria-label="Skip splash screen"
        :style="{
          border: '1px solid #27272a',
          borderRadius: '999px',
          padding: '0.7rem 1rem',
          background: 'rgba(24,24,27,0.92)',
          color: '#e4e4e7',
          fontFamily: 'JetBrains Mono, Courier New, monospace',
          fontSize: '0.75rem',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        }"
        @click.stop="skipClick"
      >
        Skip intro
      </button>

      <p
        id="dream-splash-hint"
        :style="{
          color: '#3f3f46',
          fontSize: '0.65rem',
          letterSpacing: '0.15em',
          textTransform: 'uppercase',
          fontFamily: 'monospace',
          margin: '-0.5rem 0 0',
        }"
      >
        Click or press Esc to skip
      </p>
    </div>
  </div>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>

