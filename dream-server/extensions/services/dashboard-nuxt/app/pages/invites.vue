<!--
  Invites (Phase 4 Welle B.2). Pendant zu
  dashboard/src/pages/Invites.jsx (~530 LoC). Magic-Link-Tokens
  generieren, listen, revoken; QR-Code via /api/auth/magic-link/qr.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { formatRelative, tokenStatusBadge, useInvites } from '~/composables/useInvites'
import type { GeneratedMagicLink, InviteScope } from '~/types/api'

definePageMeta({ layout: 'default' })

const { tokens, loading, refreshing, error, refresh, generate, revoke, fetchQr }
  = useInvites()

const showCreate = ref(false)
const generated = ref<GeneratedMagicLink | null>(null)

// Create form state
const username = ref('')
const scope = ref<InviteScope>('chat')
const expiresIn = ref(3600)
const reusable = ref(false)
const note = ref('')
const submitting = ref(false)
const formError = ref<string | null>(null)

const SCOPES = [{ label: 'Chat only', value: 'chat' }]
const EXPIRY_PRESETS = [
  { label: '15 minutes', value: 900 },
  { label: '1 hour', value: 3600 },
  { label: '24 hours', value: 86400 },
]

const usernameValid = computed(() => /^[A-Za-z0-9._-]+$/.test(username.value.trim()))

function resetForm() {
  username.value = ''
  scope.value = 'chat'
  expiresIn.value = 3600
  reusable.value = false
  note.value = ''
  formError.value = null
}

async function onSubmit() {
  formError.value = null
  if (!usernameValid.value) {
    formError.value = 'Username darf nur Buchstaben, Zahlen, Punkt, Bindestrich und Unterstrich enthalten.'
    return
  }
  submitting.value = true
  try {
    const out = await generate({
      target_username: username.value.trim(),
      scope: scope.value,
      expires_in: expiresIn.value,
      reusable: reusable.value,
      note: note.value.trim() || null,
    })
    showCreate.value = false
    resetForm()
    generated.value = out
  }
  catch (e: unknown) {
    formError.value = (e as Error).message
  }
  finally {
    submitting.value = false
  }
}

// QR code for the generated invite
const qrDataUrl = ref<string | null>(null)
const qrError = ref<string | null>(null)
watch(generated, async (g) => {
  qrDataUrl.value = null
  qrError.value = null
  if (!g) return
  const url = await fetchQr(g.url)
  if (url) qrDataUrl.value = url
  else qrError.value = 'QR-Generierung serverseitig nicht verfügbar.'
})

// Copy + share
const copied = ref(false)
async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  }
  catch {
    /* clipboard not available — user can ctrl-c manually */
  }
}
async function share(g: GeneratedMagicLink) {
  if (typeof navigator !== 'undefined' && 'share' in navigator) {
    try {
      await navigator.share({
        title: `Dream Server invite for ${g.target_username}`,
        text: 'Tap to open Dream Server',
        url: g.url,
      })
      return
    }
    catch { /* user cancelled */ }
  }
  copy(g.url)
}

async function onRevoke(prefix: string) {
  if (!confirm('Diesen Invite widerrufen?')) return
  try {
    await revoke(prefix)
  }
  catch (e: unknown) {
    formError.value = (e as Error).message
  }
}
</script>

<template>
  <UDashboardPanel id="invites">
    <template #header>
      <UDashboardNavbar
        title="Invites"
        description="Magic-Link-Einladungen für die Chat-Surface"
        icon="i-lucide-user-plus"
      >
        <template #leading>
          <UDashboardSidebarCollapse />
        </template>
        <template #right>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-refresh-cw"
            size="sm"
            :loading="refreshing"
            @click="refresh"
          />
          <UButton
            color="primary"
            variant="solid"
            icon="i-lucide-user-plus"
            size="sm"
            label="Neuer Invite"
            @click="showCreate = true"
          />
        </template>
      </UDashboardNavbar>
    </template>
    <template #body>
      <div class="space-y-4">
        <UAlert
          v-if="error"
          color="error"
          variant="subtle"
          icon="i-lucide-alert-triangle"
          title="Fehler"
          :description="error"
        />

        <div v-if="loading" class="space-y-3">
          <USkeleton v-for="n in 3" :key="n" class="h-20 rounded-xl" />
        </div>

        <UCard
          v-else-if="!tokens.length"
          :ui="{ body: 'p-12 text-center' }"
        >
          <UIcon name="i-lucide-users" class="mx-auto mb-3 size-10 text-muted" />
          <h3 class="mb-1 text-base font-semibold text-default">
            Noch keine Invites
          </h3>
          <p class="mx-auto mb-5 max-w-md text-sm text-muted">
            Magic-Link generieren, damit jemand vom Handy auf die Chat-Surface kommt.
            Der Link selbst ist die Credential — wie ein Passwort behandeln.
          </p>
          <UButton
            color="primary"
            icon="i-lucide-user-plus"
            label="Ersten Invite anlegen"
            @click="showCreate = true"
          />
        </UCard>

        <div v-else class="space-y-3">
          <UCard
            v-for="t in tokens"
            :key="t.token_hash_prefix"
            :ui="{ body: 'p-4' }"
          >
            <div class="flex items-center justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="mb-1 flex flex-wrap items-center gap-2">
                  <span class="font-medium text-default">{{ t.target_username }}</span>
                  <UBadge
                    :color="tokenStatusBadge(t).color"
                    variant="subtle"
                    size="sm"
                  >
                    {{ tokenStatusBadge(t).label }}
                  </UBadge>
                  <UBadge v-if="t.reusable" color="info" variant="subtle" size="sm">
                    reusable
                  </UBadge>
                  <span class="text-xs text-muted">scope: {{ t.scope }}</span>
                </div>
                <p v-if="t.note" class="mb-1 truncate text-xs text-muted">
                  {{ t.note }}
                </p>
                <div class="flex flex-wrap items-center gap-3 text-xs text-muted">
                  <span class="inline-flex items-center gap-1">
                    <UIcon name="i-lucide-clock" class="size-3" />
                    expires {{ formatRelative(t.expires_at) }}
                  </span>
                  <span v-if="formatRelative(t.last_redeemed_at)">
                    last used {{ formatRelative(t.last_redeemed_at) }}
                  </span>
                  <span class="font-mono opacity-70">{{ t.token_hash_prefix }}…</span>
                </div>
              </div>
              <UButton
                v-if="!t.revoked_at && new Date(t.expires_at).getTime() >= Date.now()"
                color="error"
                variant="ghost"
                icon="i-lucide-trash-2"
                size="sm"
                square
                :title="`Revoke ${t.target_username}`"
                @click="onRevoke(t.token_hash_prefix)"
              />
            </div>
          </UCard>
        </div>
      </div>
    </template>

    <!-- Create modal -->
    <UModal v-model:open="showCreate" :ui="{ content: 'max-w-md' }">
      <template #content>
        <UCard :ui="{ body: 'p-6' }">
          <template #header>
            <div class="flex items-center justify-between">
              <h2 class="text-base font-semibold text-default">
                Invite anlegen
              </h2>
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                size="xs"
                square
                @click="showCreate = false"
              />
            </div>
          </template>
          <form class="space-y-4" @submit.prevent="onSubmit">
            <UFormField label="Username" name="username">
              <UInput
                v-model="username"
                placeholder="alice"
                required
                autofocus
                :maxlength="64"
              />
              <template #help>
                Wird mit dem Invite gespeichert (Audit-Trail). Open WebUI fragt
                ggf. trotzdem nach Anmeldung beim ersten Aufruf.
              </template>
            </UFormField>
            <UFormField label="Access scope" name="scope">
              <USelect v-model="scope" :items="SCOPES" />
            </UFormField>
            <UFormField label="Expires in" name="expires">
              <USelect v-model="expiresIn" :items="EXPIRY_PRESETS" />
            </UFormField>
            <UCheckbox v-model="reusable" label="Reusable">
              <template #description>
                Mehrere Personen können den Link einlösen, bis er abläuft (z. B.
                Family-Share-Poster). Jede Einlösung wird geloggt.
              </template>
            </UCheckbox>
            <UFormField label="Notiz (optional)" name="note">
              <UInput v-model="note" placeholder="für Mamas iPad" :maxlength="200" />
            </UFormField>
            <UAlert
              v-if="formError"
              color="error"
              variant="subtle"
              icon="i-lucide-alert-circle"
              :description="formError"
            />
            <div class="flex justify-end gap-2 pt-2">
              <UButton color="neutral" variant="ghost" label="Cancel" @click="showCreate = false" />
              <UButton
                type="submit"
                color="primary"
                label="Generate"
                :loading="submitting"
                :disabled="!username.trim()"
              />
            </div>
          </form>
        </UCard>
      </template>
    </UModal>

    <!-- Generated reveal modal -->
    <UModal v-model:open="generated" :ui="{ content: 'max-w-lg' }">
      <template v-if="generated" #content>
        <UCard :ui="{ body: 'p-6' }">
          <template #header>
            <div class="flex items-center justify-between">
              <h2 class="text-base font-semibold text-default">
                Invite ready für {{ generated.target_username }}
              </h2>
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                size="xs"
                square
                @click="generated = null"
              />
            </div>
          </template>
          <p class="mb-4 text-sm text-muted">
            <template v-if="generated.reusable">
              Reusable-Link mit Gruppe teilen. Jede Einlösung wird geloggt.
            </template>
            <template v-else>
              Einmal-Link weitergeben. Der erste Tap konsumiert ihn.
            </template>
            Open WebUI fragt ggf. trotzdem nach Sign-in, bis SSO verdrahtet ist.
          </p>
          <div v-if="qrDataUrl" class="mb-4 flex justify-center rounded-xl bg-white p-4">
            <img :src="qrDataUrl" alt="QR code" class="h-56 w-56">
          </div>
          <div v-else class="mb-4 flex min-h-56 flex-col items-center justify-center rounded-xl border border-default p-6">
            <UIcon name="i-lucide-qr-code" class="mb-2 size-12 text-muted" />
            <p class="text-center text-xs text-muted">
              {{ qrError || 'QR-Code wird generiert…' }}
            </p>
          </div>
          <UFormField label="Invite URL">
            <div class="flex gap-2">
              <UInput
                :model-value="generated.url"
                readonly
                class="flex-1 font-mono text-xs"
                @focus="(e: FocusEvent) => (e.target as HTMLInputElement).select()"
              />
              <UButton
                :color="copied ? 'success' : 'neutral'"
                variant="outline"
                :icon="copied ? 'i-lucide-check' : 'i-lucide-copy'"
                :label="copied ? 'Copied' : 'Copy'"
                @click="copy(generated.url)"
              />
            </div>
          </UFormField>
          <div class="mt-4 flex items-center justify-between">
            <p class="text-xs text-muted">
              Expires {{ formatRelative(generated.expires_at) }}
            </p>
            <div class="flex gap-2">
              <UButton
                color="neutral"
                variant="outline"
                icon="i-lucide-share-2"
                size="sm"
                label="Share"
                @click="share(generated)"
              />
              <UButton color="primary" size="sm" label="Done" @click="generated = null" />
            </div>
          </div>
        </UCard>
      </template>
    </UModal>
  </UDashboardPanel>
</template>

