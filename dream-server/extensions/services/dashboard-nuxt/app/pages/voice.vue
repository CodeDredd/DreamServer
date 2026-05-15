<!--
  Voice (Phase 4 Welle C.2). Pendant zu dashboard/src/pages/Voice.jsx
  (~548 LoC). Talk-to-AI-Page mit LiveKit-WebRTC-Integration:
    * Service-Status-Banner (/api/voice/status, 30 s Polling)
    * Conversation-History mit User-/Assistant-Bubbles
    * Großer Mic-Button (Toggle Listening), Spacebar-Push-to-Talk
    * Volume + Mute-Slider, Settings-Modal (localStorage-persistiert)
    * Audio-Waveform-Animation während Speaking
  livekit-client wird per dynamic import geladen — falls nicht
  installiert, faengt der Catch im Composable und zeigt's im Banner.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useVoiceAgent } from '~/composables/useVoiceAgent'
import { useVoiceServices } from '~/composables/useVoiceServices'

definePageMeta({ layout: 'default' })

const { services, loading: servicesLoading, refresh: refreshServices } = useVoiceServices()

const {
  status,
  isListening,
  isSpeaking,
  messages,
  currentTranscript,
  error,
  volume,
  isMuted,
  toggleListening,
  toggleMute,
  updateVolume,
  interrupt,
  clearMessages,
} = useVoiceAgent()

// ---------- Status indicator ------------------------------------------

const statusInfo = computed(() => {
  switch (status.value) {
    case 'connecting':
      return { text: 'Connecting…', color: 'text-warning', icon: 'i-lucide-loader-2', spin: true }
    case 'connected':
      return { text: 'Connected', color: 'text-success', icon: 'i-lucide-radio', spin: false }
    case 'error':
      return { text: 'Error', color: 'text-error', icon: 'i-lucide-alert-circle', spin: false }
    default:
      return { text: 'Ready', color: 'text-toned', icon: 'i-lucide-radio', spin: false }
  }
})

// ---------- Conversation auto-scroll ----------------------------------

const conversationEnd = ref<HTMLElement | null>(null)
watch([messages, currentTranscript], () => {
  void nextTick(() => {
    conversationEnd.value?.scrollIntoView({ behavior: 'smooth' })
  })
})

// ---------- Push-to-talk (spacebar) -----------------------------------

function onKeyDown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement | null)?.tagName
  if (e.code === 'Space' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
    e.preventDefault()
    if (!isListening.value && status.value !== 'connecting') {
      void toggleListening()
    }
  }
  if (e.code === 'Escape' && isSpeaking.value) interrupt()
}

onMounted(() => window.addEventListener('keydown', onKeyDown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeyDown))

// ---------- Settings modal --------------------------------------------

const showSettings = ref(false)

interface VoiceSettings {
  voice: string
  speed: number
  wakeWord: boolean
}

const settings = ref<VoiceSettings>({ voice: 'default', speed: 1.0, wakeWord: false })
const settingsDraft = ref<VoiceSettings>({ ...settings.value })

onMounted(() => {
  if (typeof localStorage === 'undefined') return
  settings.value = {
    voice: localStorage.getItem('voice-setting') || 'default',
    speed: parseFloat(localStorage.getItem('voice-speed') || '1') || 1.0,
    wakeWord: localStorage.getItem('voice-wake') === 'true',
  }
})

watch(showSettings, (open) => {
  if (open) settingsDraft.value = { ...settings.value }
})

function saveSettings() {
  settings.value = { ...settingsDraft.value }
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem('voice-setting', settings.value.voice)
    localStorage.setItem('voice-speed', settings.value.speed.toString())
    localStorage.setItem('voice-wake', settings.value.wakeWord.toString())
  }
  showSettings.value = false
}

const voiceOptions = [
  { label: 'Default (LJSpeech)', value: 'default' },
  { label: 'Jenny (Female)', value: 'jenny' },
  { label: 'Alan (Male)', value: 'alan' },
  { label: 'Amy (British)', value: 'amy' },
]

// ---------- Helpers ----------------------------------------------------

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString()
}

function probeOk(name: 'stt' | 'tts' | 'livekit'): boolean {
  return services.value?.services?.[name]?.status === 'healthy'
}
</script>

<template>
  <UDashboardPanel id="voice">
    <template #header>
      <UDashboardNavbar
        title="Voice"
        description="Talk to your AI. Like having your own Jarvis."
        icon="i-lucide-mic"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <span class="flex items-center gap-2 text-sm" :class="statusInfo.color">
            <UIcon
              :name="statusInfo.icon"
              :class="['size-4', statusInfo.spin ? 'animate-spin' : '']"
            />
            {{ statusInfo.text }}
          </span>
          <!-- Volume control -->
          <div class="flex items-center gap-2">
            <UButton
              :icon="isMuted ? 'i-lucide-volume-x' : 'i-lucide-volume-2'"
              color="neutral"
              variant="ghost"
              size="sm"
              square
              @click="toggleMute"
            />
            <input
              type="range"
              min="0"
              max="1"
              step="0.1"
              :value="isMuted ? 0 : volume"
              class="w-24 accent-primary"
              @input="updateVolume(parseFloat(($event.target as HTMLInputElement).value))"
            >
          </div>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-settings"
            size="sm"
            square
            @click="showSettings = true"
          />
        </template>
      </UDashboardNavbar>
    </template>

    <template #body>
      <div class="flex h-[calc(100vh-8rem)] flex-col">
        <!-- Voice Services Banner -->
        <div class="px-2 pb-3 pt-1">
          <UAlert
            v-if="servicesLoading"
            color="neutral"
            variant="subtle"
            icon="i-lucide-loader-2"
            title="Checking voice services…"
          />
          <UAlert
            v-else-if="services && services.available"
            color="success"
            variant="subtle"
            icon="i-lucide-check-circle"
            title="Voice services ready"
            :description="`STT ✓ · TTS ✓ · LiveKit ✓`"
          />
          <UAlert
            v-else-if="services"
            color="warning"
            variant="subtle"
            icon="i-lucide-alert-circle"
            title="Some voice services unavailable"
            :actions="[
              { label: 'Refresh', color: 'warning', variant: 'subtle', onClick: () => refreshServices() },
            ]"
          >
            <template #description>
              <div class="space-y-2">
                <div class="flex flex-wrap items-center gap-3 text-xs">
                  <span :class="probeOk('stt') ? 'text-success' : 'text-error'">
                    {{ probeOk('stt') ? '✓' : '✗' }} Whisper (STT)
                  </span>
                  <span :class="probeOk('tts') ? 'text-success' : 'text-error'">
                    {{ probeOk('tts') ? '✓' : '✗' }} Kokoro (TTS)
                  </span>
                  <span :class="probeOk('livekit') ? 'text-success' : 'text-error'">
                    {{ probeOk('livekit') ? '✓' : '✗' }} LiveKit
                  </span>
                </div>
                <p class="text-xs text-muted">
                  Check voice services:
                  <code class="text-toned">docker compose ps whisper tts</code>
                </p>
              </div>
            </template>
          </UAlert>
        </div>

        <!-- Conversation Area -->
        <div class="flex-1 space-y-3 overflow-y-auto px-2 py-4">
          <!-- Empty state -->
          <div
            v-if="!messages.length && !currentTranscript"
            class="flex h-full flex-col items-center justify-center text-center"
          >
            <div class="mb-4 flex size-24 items-center justify-center rounded-full bg-elevated">
              <UIcon name="i-lucide-mic" class="size-10 text-muted" />
            </div>
            <h3 class="mb-2 text-lg text-default">
              Start a conversation
            </h3>
            <p class="max-w-md text-sm text-muted">
              Click the microphone button below to start talking. Your AI will listen,
              understand, and respond with voice.
            </p>
          </div>

          <!-- Messages -->
          <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="flex"
            :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div
              class="max-w-[80%] rounded-2xl px-4 py-3"
              :class="msg.role === 'user'
                ? 'rounded-br-none bg-primary text-inverted'
                : 'rounded-bl-none bg-elevated text-default'"
            >
              <p class="text-sm">
                {{ msg.content }}
              </p>
              <span class="mt-1 block text-xs opacity-50">{{ fmtTime(msg.timestamp) }}</span>
            </div>
          </div>

          <!-- Interim transcript -->
          <div v-if="currentTranscript" class="flex justify-end">
            <div class="max-w-[80%] rounded-2xl rounded-br-none border border-primary/30 bg-primary/40 px-4 py-3 text-inverted">
              <p class="text-sm italic">
                {{ currentTranscript }}
              </p>
            </div>
          </div>

          <!-- AI speaking indicator -->
          <div v-if="isSpeaking" class="flex justify-start">
            <div class="flex items-center gap-3 rounded-2xl rounded-bl-none bg-elevated px-4 py-3">
              <div class="flex h-8 items-end gap-1">
                <span
                  v-for="i in 5"
                  :key="i"
                  class="block w-1 animate-pulse rounded-full bg-primary"
                  :style="{ height: `${20 + ((i * 17) % 60)}%`, animationDelay: `${i * 0.1}s` }"
                />
              </div>
              <span class="text-sm text-muted">AI is speaking…</span>
            </div>
          </div>

          <div ref="conversationEnd" />
        </div>

        <!-- Error banner -->
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-alert-circle"
          title="Connection Error"
          class="mx-2 mb-3"
        >
          <template #description>
            <p>{{ error }}</p>
            <p class="mt-1 text-xs text-muted">
              Make sure LiveKit server is running and voice services are enabled.
            </p>
          </template>
        </UAlert>

        <!-- Control Bar -->
        <div class="border-t border-default bg-elevated/30 px-6 py-5">
          <div class="flex items-center justify-center gap-4">
            <UButton
              v-if="messages.length"
              color="neutral"
              variant="ghost"
              icon="i-lucide-trash-2"
              size="lg"
              square
              title="Clear conversation"
              @click="clearMessages"
            />
            <button
              type="button"
              :disabled="status === 'connecting'"
              class="flex size-20 items-center justify-center rounded-full shadow-lg transition-all"
              :class="[
                status === 'connecting' ? 'cursor-not-allowed bg-muted'
                : isListening ? 'bg-error scale-110 hover:bg-error/90'
                  : 'bg-primary hover:bg-primary/90 hover:scale-105',
              ]"
              @click="toggleListening"
            >
              <UIcon
                v-if="status === 'connecting'"
                name="i-lucide-loader-2"
                class="size-8 animate-spin text-inverted"
              />
              <UIcon
                v-else-if="isListening"
                name="i-lucide-mic-off"
                class="size-8 text-inverted"
              />
              <UIcon v-else name="i-lucide-mic" class="size-8 text-inverted" />
            </button>
            <UButton
              v-if="isSpeaking"
              color="neutral"
              variant="ghost"
              icon="i-lucide-stop-circle"
              size="lg"
              square
              title="Interrupt AI"
              @click="interrupt"
            />
          </div>

          <p class="mt-4 text-center text-sm text-muted">
            {{ status === 'connecting'
              ? 'Connecting to voice server…'
              : isListening
                ? 'Listening… Click to stop'
                : 'Click to start talking' }}
          </p>
          <p class="mt-2 text-center text-xs text-muted">
            Tip: Hold
            <kbd class="rounded bg-elevated px-1.5 py-0.5 font-mono text-xs text-toned">Space</kbd>
            to talk
          </p>
        </div>
      </div>
    </template>

    <!-- Settings modal -->
    <UModal v-model:open="showSettings" :ui="{ width: 'sm:max-w-md' }">
      <template #content>
        <UCard>
          <template #header>
            <h3 class="text-lg font-semibold">
              Voice Settings
            </h3>
          </template>
          <div class="space-y-4">
            <UFormField label="Voice" name="voice">
              <USelect v-model="settingsDraft.voice" :items="voiceOptions" class="w-full" />
            </UFormField>
            <UFormField :label="`Speech Speed: ${settingsDraft.speed.toFixed(1)}x`" name="speed">
              <input
                v-model.number="settingsDraft.speed"
                type="range"
                min="0.5"
                max="2"
                step="0.1"
                class="w-full accent-primary"
              >
            </UFormField>
            <div class="flex items-center justify-between">
              <div>
                <p class="text-sm text-default">
                  Wake Word
                </p>
                <p class="text-xs text-muted">
                  Say "Hey Dream" to activate
                </p>
              </div>
              <USwitch v-model="settingsDraft.wakeWord" />
            </div>
          </div>
          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton color="neutral" variant="ghost" @click="showSettings = false">
                Cancel
              </UButton>
              <UButton color="primary" @click="saveSettings">
                Save
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>
  </UDashboardPanel>
</template>

