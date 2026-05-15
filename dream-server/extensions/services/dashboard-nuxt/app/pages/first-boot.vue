<!--
  First-Boot Wizard (Phase 4 Welle D). Pendant zu
  dashboard/src/pages/FirstBoot.jsx (~581 LoC). Phone-first 4-Step-
  Wizard, der bei firstRun=true ueber middleware/first-run.global.ts
  als einzig erreichbare Route bleibt.

  4 Steps:
    1. Welcome — Setup-Label
    2. First user — Username fuer initiale Magic-Link-Invite
    3. Stack-Picker — chat / chat+agents / everything (Praeferenz, kein Side-Effect)
    4. Confirm & Finish — generiert Magic-Link, POST /api/setup/complete
  + DoneScreen mit QR + Copy + Share-API.

  Progress in localStorage gespiegelt, damit Mobile-Refresh keinen
  Datenverlust verursacht.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useApi } from '~/composables/useApi'
import { useFirstRun } from '~/composables/useFirstRun'
import type {
  GeneratedMagicLink,
  MagicLinkQrResponse,
} from '~/types/api'

definePageMeta({
  // FirstBoot ist eine eigenstaendige Vollbild-Page — kein
  // Dashboard-Layout (keine Sidebar / Navbar).
  layout: false,
})

const PROGRESS_KEY = 'dream-firstboot-progress'
const TOTAL_STEPS = 4

interface ProgressSnapshot {
  step?: number
  deviceName?: string
  username?: string
  stack?: StackId
}

type StackId = 'chat' | 'chat-agents' | 'everything'

interface StackOption {
  id: StackId
  title: string
  blurb: string
  icon: string
}

const STACK_OPTIONS: StackOption[] = [
  {
    id: 'chat',
    title: 'Chat only',
    blurb: 'Just the chat surface. This is what runs out of the box.',
    icon: 'i-lucide-message-square',
  },
  {
    id: 'chat-agents',
    title: 'Chat + Agents',
    blurb: 'Adds n8n workflows and the agent runtime; enable from Extensions after setup.',
    icon: 'i-lucide-workflow',
  },
  {
    id: 'everything',
    title: 'Everything',
    blurb: 'Voice, image generation, search, the whole catalog; enable from Extensions after setup.',
    icon: 'i-lucide-boxes',
  },
]

function readProgress(): ProgressSnapshot {
  try {
    const raw = globalThis.localStorage?.getItem(PROGRESS_KEY)
    return raw ? (JSON.parse(raw) as ProgressSnapshot) : {}
  }
  catch {
    return {}
  }
}
function writeProgress(p: ProgressSnapshot): void {
  try {
    globalThis.localStorage?.setItem(PROGRESS_KEY, JSON.stringify(p))
  }
  catch {
    /* localStorage may be blocked in private windows */
  }
}
function clearProgress(): void {
  try {
    globalThis.localStorage?.removeItem(PROGRESS_KEY)
  }
  catch { /* ignore */ }
}

const initial = readProgress()
const step = ref<number>(initial.step ?? 1)
const deviceName = ref<string>(initial.deviceName ?? 'dream')
const username = ref<string>(initial.username ?? '')
const stack = ref<StackId>(initial.stack ?? 'chat')
const finishing = ref(false)
const finishError = ref<string | null>(null)
const invite = ref<GeneratedMagicLink | null>(null)

// Persist on every change.
watch([step, deviceName, username, stack], () => {
  writeProgress({
    step: step.value,
    deviceName: deviceName.value,
    username: username.value,
    stack: stack.value,
  })
})

function next(): void {
  step.value = Math.min(step.value + 1, TOTAL_STEPS)
}
function prev(): void {
  step.value = Math.max(step.value - 1, 1)
}

const deviceValid = computed(() =>
  /^[a-z0-9-]{1,32}$/i.test(deviceName.value.trim()),
)
const usernameValid = computed(() =>
  /^[A-Za-z0-9._-]{1,64}$/.test(username.value.trim()),
)
const stackTitle = computed(
  () => STACK_OPTIONS.find(s => s.id === stack.value)?.title ?? stack.value,
)

const api = useApi()
const firstRun = useFirstRun()

async function finish(): Promise<void> {
  finishing.value = true
  finishError.value = null
  try {
    const inviteData = await api.post<GeneratedMagicLink>(
      '/api/auth/magic-link/generate',
      {
        target_username: username.value.trim(),
        scope: 'chat',
        expires_in: 86400,
        reusable: false,
        note: `First-boot invite (${deviceName.value.trim() || 'dream'})`,
      },
    )

    // Server-side Sentinel kippen — wenn das fehlschlaegt, surface
    // den Fehler trotzdem (Invite ist bereits gespeichert).
    try {
      await api.post('/api/setup/complete', {})
    }
    catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      throw new Error(
        `Failed to mark setup complete: ${msg}. Your invite was generated; ask the admin to re-run setup.`,
      )
    }

    invite.value = inviteData
    clearProgress()
    // Setup-Store updaten, damit die Middleware bei "Open dashboard"
    // nicht wieder hierher umlenkt.
    await firstRun.refresh()
  }
  catch (err: unknown) {
    finishError.value = err instanceof Error ? err.message : String(err)
  }
  finally {
    finishing.value = false
  }
}

function handleDone(): void {
  // Middleware leitet automatisch nach / um, sobald firstRun=false.
  void navigateTo('/', { replace: true })
}

// ---------- Done-Screen-State ----------
const qrDataUrl = ref<string | null>(null)
const qrError = ref<string | null>(null)
const copied = ref(false)
const canShare = ref(false)

onMounted(() => {
  canShare.value = typeof navigator !== 'undefined' && !!navigator.share
})

watch(invite, async (val) => {
  if (!val) return
  qrDataUrl.value = null
  qrError.value = null
  try {
    const data = await api.get<MagicLinkQrResponse>(
      `/api/auth/magic-link/qr?url=${encodeURIComponent(val.url)}`,
    )
    qrDataUrl.value = data.data_url
  }
  catch (e: unknown) {
    qrError.value = e instanceof Error ? e.message : 'QR generation unavailable on the server.'
  }
})

async function copyInvite(): Promise<void> {
  if (!invite.value) return
  try {
    await navigator.clipboard.writeText(invite.value.url)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  }
  catch { /* fallback: input ist selectable */ }
}

async function shareInvite(): Promise<void> {
  if (!invite.value) return
  if (!navigator.share) {
    void copyInvite()
    return
  }
  try {
    await navigator.share({
      title: `Dream Server invite for ${invite.value.target_username}`,
      text: 'Tap to open Dream Server',
      url: invite.value.url,
    })
  }
  catch { /* user cancelled */ }
}

function selectInputText(e: FocusEvent): void {
  const target = e.target as HTMLInputElement | null
  target?.select()
}
</script>

<template>
  <div class="min-h-screen bg-default flex flex-col">
    <header class="px-6 pt-8 pb-4 flex items-center justify-between">
      <div class="font-mono text-sm font-bold text-primary tracking-widest">
        DREAM SERVER
      </div>
      <!-- StepDots -->
      <div v-if="!invite" class="flex items-center gap-2">
        <div
          v-for="n in TOTAL_STEPS"
          :key="n"
          :class="[
            'w-2 h-2 rounded-full transition-colors',
            n < step
              ? 'bg-primary'
              : n === step
                ? 'bg-primary ring-2 ring-primary/40'
                : 'bg-default',
          ]"
        />
      </div>
    </header>

    <main class="flex-1 flex items-stretch px-6 pb-8">
      <div class="w-full max-w-md mx-auto flex flex-col justify-center">
        <!-- ---- DoneScreen ---- -->
        <div v-if="invite">
          <div class="w-16 h-16 rounded-2xl bg-success/15 text-success flex items-center justify-center mb-6">
            <UIcon name="i-lucide-check" class="size-8" />
          </div>
          <h1 class="text-3xl font-bold text-default mb-3">
            You&apos;re set.
          </h1>
          <p class="text-muted mb-6 leading-relaxed">
            Here&apos;s the magic link for
            <strong class="text-default">{{ invite.target_username }}</strong>.
            They scan or tap it to reach the chat surface.
            (Open WebUI may still prompt for a sign-in until SSO is wired up.)
          </p>

          <div
            v-if="qrDataUrl"
            class="bg-white p-4 rounded-xl flex justify-center mb-6"
          >
            <img
              :src="qrDataUrl"
              alt="QR code for invite link"
              class="w-56 h-56"
            >
          </div>
          <div
            v-else
            class="bg-elevated border border-default rounded-xl p-8 flex flex-col items-center justify-center mb-6 min-h-56"
          >
            <UIcon name="i-lucide-qr-code" class="size-12 text-muted mb-2" />
            <p class="text-xs text-muted text-center">
              {{ qrError || 'Generating QR…' }}
            </p>
          </div>

          <div class="flex gap-2 mb-6">
            <input
              :value="invite.url"
              readonly
              class="flex-1 bg-elevated border border-default rounded-lg px-3 py-2 text-xs font-mono text-default"
              @focus="selectInputText"
            >
            <button
              type="button"
              class="flex items-center gap-1 px-3 py-2 bg-elevated border border-default rounded-lg text-default hover:bg-default text-sm"
              title="Copy link"
              aria-label="Copy invite link"
              @click="copyInvite"
            >
              <UIcon
                v-if="copied"
                name="i-lucide-check"
                class="size-4 text-success"
              />
              <UIcon v-else name="i-lucide-copy" class="size-4" />
            </button>
          </div>

          <div class="flex gap-3">
            <UButton
              v-if="canShare"
              variant="outline"
              color="neutral"
              size="xl"
              icon="i-lucide-share-2"
              class="flex-1 justify-center"
              @click="shareInvite"
            >
              Share
            </UButton>
            <UButton
              color="primary"
              size="xl"
              class="flex-1 justify-center"
              @click="handleDone"
            >
              Open dashboard
            </UButton>
          </div>

          <p class="text-xs text-muted mt-6 text-center">
            Need more invites later? They live under
            <strong>Invites</strong> in the sidebar.
          </p>
        </div>

        <!-- ---- Step 1: Welcome ---- -->
        <div v-else-if="step === 1">
          <div class="w-16 h-16 rounded-2xl bg-primary/15 text-primary flex items-center justify-center mb-6">
            <UIcon name="i-lucide-sparkles" class="size-8" />
          </div>
          <h1 class="text-3xl font-bold text-default mb-3">
            Welcome to Dream.
          </h1>
          <p class="text-muted mb-8 leading-relaxed">
            Let&apos;s get you set up in about a minute. First, give this
            setup a friendly label for the invite audit trail.
          </p>

          <label class="block mb-6">
            <span class="text-sm text-muted">Setup label</span>
            <input
              v-model="deviceName"
              type="text"
              autofocus
              maxlength="32"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              class="mt-2 w-full bg-elevated border border-default rounded-xl px-4 py-3 text-lg text-default focus:outline-none focus:border-primary"
            >
            <span class="text-xs text-muted mt-2 block">
              This label is recorded on the first invite only. It does not
              rename the host yet; change
              <code class="text-primary">DREAM_DEVICE_NAME</code> in Settings
              before expecting
              <code class="text-primary"> {{ deviceName.trim() || 'dream' }}.local</code>
              to resolve. Letters, numbers, and dashes only.
            </span>
          </label>

          <UButton
            color="primary"
            size="xl"
            class="w-full justify-center"
            :disabled="!deviceValid"
            trailing-icon="i-lucide-chevron-right"
            @click="next"
          >
            Continue
          </UButton>
        </div>

        <!-- ---- Step 2: First user ---- -->
        <div v-else-if="step === 2">
          <div class="w-16 h-16 rounded-2xl bg-primary/15 text-primary flex items-center justify-center mb-6">
            <UIcon name="i-lucide-user" class="size-8" />
          </div>
          <h1 class="text-3xl font-bold text-default mb-3">
            Who&apos;s the first user?
          </h1>
          <p class="text-muted mb-8 leading-relaxed">
            We&apos;ll generate a magic link for them at the end. They scan
            it once to reach the chat surface.
          </p>

          <label class="block mb-6">
            <span class="text-sm text-muted">Username</span>
            <input
              v-model="username"
              type="text"
              autofocus
              maxlength="64"
              placeholder="alice"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              class="mt-2 w-full bg-elevated border border-default rounded-xl px-4 py-3 text-lg text-default focus:outline-none focus:border-primary"
            >
            <span class="text-xs text-muted mt-2 block">
              Recorded with the invite for the audit trail. Open WebUI may
              still ask the recipient to sign in or pick a profile name on
              first arrival.
            </span>
          </label>

          <div class="flex gap-3">
            <UButton
              variant="outline"
              color="neutral"
              size="xl"
              icon="i-lucide-chevron-left"
              aria-label="Back"
              @click="prev"
            />
            <UButton
              color="primary"
              size="xl"
              class="flex-1 justify-center"
              :disabled="!usernameValid"
              trailing-icon="i-lucide-chevron-right"
              @click="next"
            >
              Continue
            </UButton>
          </div>
        </div>

        <!-- ---- Step 3: Stack picker ---- -->
        <div v-else-if="step === 3">
          <div class="w-16 h-16 rounded-2xl bg-primary/15 text-primary flex items-center justify-center mb-6">
            <UIcon name="i-lucide-layers" class="size-8" />
          </div>
          <h1 class="text-3xl font-bold text-default mb-3">
            Pick your stack.
          </h1>
          <p class="text-muted mb-6 leading-relaxed">
            You can change this later. Start small if you want and add things
            as you go.
          </p>

          <div class="space-y-3 mb-8">
            <button
              v-for="opt in STACK_OPTIONS"
              :key="opt.id"
              type="button"
              :class="[
                'w-full text-left p-4 rounded-xl border-2 transition-colors flex gap-4',
                stack === opt.id
                  ? 'border-primary bg-primary/10'
                  : 'border-default bg-elevated hover:border-muted',
              ]"
              @click="stack = opt.id"
            >
              <div
                :class="[
                  'w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0',
                  stack === opt.id
                    ? 'bg-primary text-inverted'
                    : 'bg-default text-muted',
                ]"
              >
                <UIcon :name="opt.icon" class="size-6" />
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between">
                  <span class="font-medium text-default">{{ opt.title }}</span>
                  <UIcon
                    v-if="stack === opt.id"
                    name="i-lucide-check"
                    class="size-5 text-primary flex-shrink-0"
                  />
                </div>
                <p class="text-sm text-muted mt-1">
                  {{ opt.blurb }}
                </p>
              </div>
            </button>
          </div>

          <div class="flex gap-3">
            <UButton
              variant="outline"
              color="neutral"
              size="xl"
              icon="i-lucide-chevron-left"
              aria-label="Back"
              @click="prev"
            />
            <UButton
              color="primary"
              size="xl"
              class="flex-1 justify-center"
              trailing-icon="i-lucide-chevron-right"
              @click="next"
            >
              Continue
            </UButton>
          </div>
        </div>

        <!-- ---- Step 4: Confirm & finish ---- -->
        <div v-else-if="step === 4">
          <h1 class="text-3xl font-bold text-default mb-6">
            Ready?
          </h1>
          <p class="text-muted mb-6 leading-relaxed">
            Tap Finish and we&apos;ll generate the first invite. Bring it up
            on a phone or share the QR.
          </p>

          <dl class="bg-elevated border border-default rounded-xl divide-y divide-default mb-8">
            <div class="px-4 py-3 flex items-center justify-between gap-4">
              <span class="text-sm text-muted">Setup label</span>
              <span class="text-default font-medium text-right">
                {{ deviceName.trim() || 'dream' }}
                <span class="text-xs text-muted block font-normal">
                  invite audit note
                </span>
              </span>
            </div>
            <div class="px-4 py-3 flex items-center justify-between gap-4">
              <span class="text-sm text-muted">First user</span>
              <span class="text-default font-medium text-right">
                {{ username.trim() }}
              </span>
            </div>
            <div class="px-4 py-3 flex items-center justify-between gap-4">
              <span class="text-sm text-muted">Stack</span>
              <span class="text-default font-medium text-right">
                {{ stackTitle }}
                <span class="text-xs text-muted block font-normal">
                  enable extras from Extensions
                </span>
              </span>
            </div>
          </dl>

          <UAlert
            v-if="finishError"
            color="error"
            variant="soft"
            icon="i-lucide-alert-circle"
            class="mb-6"
            :description="finishError"
          />

          <div class="flex gap-3">
            <UButton
              variant="outline"
              color="neutral"
              size="xl"
              icon="i-lucide-chevron-left"
              :disabled="finishing"
              aria-label="Back"
              @click="prev"
            />
            <UButton
              color="primary"
              size="xl"
              class="flex-1 justify-center"
              :loading="finishing"
              :disabled="finishing"
              @click="finish"
            >
              {{ finishing ? 'Finishing…' : 'Finish' }}
            </UButton>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

