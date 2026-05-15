<!--
  Environment Editor (Phase 4 Welle A.5). Pendant zu
  dashboard/src/components/settings/EnvEditor.jsx (~312 LoC) plus
  der State-/Save-/Apply-Logik aus Settings.jsx.

  Layout: Two-Column-Grid (Sektionen-Sidebar + Field-Liste), Toolbar
  oben mit Reload/Save/Apply, Hint-Strip mit drei Karten,
  Validation-Notes.
-->
<script setup lang="ts">
import { defineComponent, h, onMounted } from 'vue'
import { useEnvEditor } from '~/composables/useEnvEditor'
import type { EnvFieldDef } from '~/types/api'

const env = useEnvEditor()

onMounted(() => {
  if (!env.editor.value) void env.refresh()
})

// ---------- Inline-Helper-Components ----------

const Chip = defineComponent({
  name: 'EnvEditorChip',
  props: { accent: { type: Boolean, default: false } },
  setup(props, { slots }) {
    return () =>
      h(
        'span',
        {
          class: [
            'rounded-full border px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.16em]',
            props.accent
              ? 'border-primary/20 bg-primary/10 text-default'
              : 'border-default bg-elevated/40 text-muted',
          ],
        },
        slots.default?.(),
      )
  },
})

const Badge = defineComponent({
  name: 'EnvEditorBadge',
  props: { muted: { type: Boolean, default: false } },
  setup(props, { slots }) {
    return () =>
      h(
        'span',
        {
          class: [
            'rounded-full border px-2 py-0.5 text-[10px] font-mono uppercase tracking-[0.14em]',
            props.muted
              ? 'border-default bg-elevated/40 text-muted/75'
              : 'border-primary/20 bg-primary/10 text-default',
          ],
        },
        slots.default?.(),
      )
  },
})

function fieldDefault(field: EnvFieldDef | undefined): string {
  if (!field) return ''
  if (field.default === undefined || field.default === null) return ''
  return String(field.default)
}

function secretPlaceholder(field: EnvFieldDef | undefined): string {
  if (!field) return ''
  if (field.secret) return field.hasValue ? 'Stored locally' : 'Not set'
  return fieldDefault(field)
}

function applyHintText(): string {
  if (env.editor.value?.agentAvailable === false) {
    return 'Dream host agent is offline. Start it first, then use Apply changes to recreate affected services.'
  }
  if (env.canApply.value) {
    return `Apply changes will recreate: ${env.applyPlan.value?.services?.join(', ') ?? '—'}.`
  }
  return 'Apply changes becomes available after saving keys that affect running services.'
}
</script>

<template>
  <div class="space-y-4">
    <!-- Header / Toolbar -->
    <div class="rounded-2xl border border-default bg-elevated px-4 py-4">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
            Local configuration
          </p>
          <p class="mt-1 text-sm text-default">
            Edit the DreamServer <code>.env</code> directly from the dashboard.
          </p>
          <p
            v-if="env.editor.value?.path"
            class="mt-2 break-all font-mono text-[11px] text-muted"
          >
            {{ env.editor.value.path }}
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <UButton
            variant="outline"
            color="neutral"
            size="sm"
            icon="i-lucide-refresh-cw"
            label="Reload"
            :loading="env.loading.value"
            @click="env.refresh({ announce: true })"
          />
          <UButton
            color="primary"
            size="sm"
            icon="i-lucide-save"
            :loading="env.saving.value"
            :disabled="!env.dirty.value || env.saving.value"
            :label="env.saving.value ? 'Saving…' : 'Save .env'"
            @click="env.save()"
          />
          <UButton
            variant="outline"
            color="neutral"
            size="sm"
            icon="i-lucide-rocket"
            :loading="env.applying.value"
            :disabled="!env.canApply.value || env.applying.value || env.saving.value"
            :label="env.applying.value ? 'Applying…' : 'Apply changes'"
            @click="env.apply()"
          />
        </div>
      </div>

      <div class="mt-4 flex flex-wrap gap-2">
        <Chip>{{ Object.keys(env.fields.value).length }} fields</Chip>
        <Chip>
          {{ env.issues.value.length }} validation issue{{ env.issues.value.length === 1 ? '' : 's' }}
        </Chip>
        <Chip v-if="env.editor.value?.backupPath" accent>
          last backup {{ env.editor.value.backupPath }}
        </Chip>
        <Chip
          v-if="env.applyPlan.value?.status && env.applyPlan.value.status !== 'none'"
          accent
        >
          {{ env.applyPlan.value.status }}
        </Chip>
      </div>
    </div>

    <!-- Notice (info / warn / danger) -->
    <UAlert
      v-if="env.notice.value"
      :color="
        env.notice.value.tone === 'danger'
          ? 'error'
          : env.notice.value.tone === 'warn'
            ? 'warning'
            : 'primary'
      "
      variant="subtle"
      :description="env.notice.value.text"
      :close="true"
      @close="env.dismissNotice()"
    />

    <!-- Pending runtime changes -->
    <div
      v-if="env.applyPlan.value?.status && env.applyPlan.value.status !== 'none'"
      class="rounded-xl border border-primary/20 bg-primary/10 px-4 py-3"
    >
      <p class="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
        Pending runtime changes
      </p>
      <p class="mt-1 text-sm text-default">
        {{ env.applyPlan.value.summary }}
      </p>
    </div>

    <!-- Hints (3-Card-Grid) -->
    <div class="grid gap-3 sm:grid-cols-3">
      <div class="rounded-xl border border-default bg-elevated/40 px-4 py-3">
        <p class="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted/60">
          Save behavior
        </p>
        <p class="mt-1 text-sm text-muted">
          {{ env.editor.value?.saveHint || 'Writes the .env file in place and creates a timestamped backup.' }}
        </p>
      </div>
      <div class="rounded-xl border border-default bg-elevated/40 px-4 py-3">
        <p class="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted/60">
          Restart behavior
        </p>
        <p class="mt-1 text-sm text-muted">
          {{ env.editor.value?.restartHint || 'Some keys require restarting the affected services.' }}
        </p>
      </div>
      <div class="rounded-xl border border-default bg-elevated/40 px-4 py-3">
        <p class="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted/60">
          Apply behavior
        </p>
        <p class="mt-1 text-sm text-muted">
          {{ applyHintText() }}
        </p>
      </div>
    </div>

    <!-- Validation notes (max. 8) -->
    <div
      v-if="env.issues.value.length > 0"
      class="rounded-xl border border-warning/20 bg-warning/10 px-4 py-3"
    >
      <p class="text-[10px] font-semibold uppercase tracking-[0.18em] text-warning">
        Validation notes
      </p>
      <div class="mt-2 space-y-1">
        <p
          v-for="(issue, index) in env.issues.value.slice(0, 8)"
          :key="`${issue.key || 'line'}-${index}`"
          class="text-sm text-warning/90"
        >
          <template v-if="issue.key">
            {{ issue.key }}:
          </template>
          {{ issue.message }}
        </p>
      </div>
    </div>

    <!-- Two-Column-Grid: Sektionen + Fields -->
    <div class="grid gap-4 xl:grid-cols-[240px_1fr]">
      <!-- Sektionen-Sidebar -->
      <div class="self-start rounded-2xl border border-default bg-elevated px-3 py-3 xl:sticky xl:top-6">
        <label class="flex items-center gap-2 rounded-xl border border-default bg-default px-3 py-2">
          <span class="sr-only">Filter configuration fields</span>
          <UIcon name="i-lucide-search" class="size-3.5 text-muted" />
          <input
            v-model="env.search.value"
            placeholder="Filter fields…"
            aria-label="Filter configuration fields"
            class="w-full bg-transparent text-sm text-default outline-none placeholder:text-muted/55"
          >
        </label>
        <div class="mt-3 max-h-[60vh] overflow-y-auto pr-1">
          <button
            v-for="section in env.filteredSections.value"
            :key="section.id"
            type="button"
            :aria-pressed="env.activeSection.value?.id === section.id"
            :class="[
              'group relative flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left transition-colors',
              env.activeSection.value?.id === section.id
                ? 'bg-primary/10 text-default'
                : 'text-muted hover:bg-default hover:text-default',
            ]"
            @click="env.activeSectionId.value = section.id"
          >
            <span
              :class="[
                'absolute bottom-1.5 left-0 top-1.5 w-px rounded-full transition-colors',
                env.activeSection.value?.id === section.id
                  ? 'bg-primary'
                  : 'bg-transparent group-hover:bg-default',
              ]"
            />
            <span class="min-w-0 pl-2">
              <span class="block truncate text-sm font-medium">
                {{ section.title }}
              </span>
            </span>
            <span
              :class="[
                'shrink-0 text-[10px] font-mono uppercase tracking-[0.14em]',
                env.activeSection.value?.id === section.id
                  ? 'text-primary'
                  : 'text-muted/55',
              ]"
            >
              {{ section.keys.length }}
            </span>
          </button>
        </div>
      </div>

      <!-- Active-Section Body -->
      <div class="flex h-[30rem] flex-col rounded-2xl border border-default bg-elevated px-4 py-4">
        <template v-if="env.activeSection.value">
          <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <p class="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted/60">
                {{ env.activeSection.value.id }}
              </p>
              <h3 class="mt-1 text-lg font-semibold text-default">
                {{ env.activeSection.value.title }}
              </h3>
            </div>
            <Chip>{{ env.activeSection.value.keys.length }} fields</Chip>
          </div>

          <div class="min-h-0 overflow-y-auto pr-1">
            <div class="space-y-3">
              <div
                v-for="key in env.activeSection.value.keys"
                :key="key"
                :class="[
                  'rounded-2xl border px-4 py-3',
                  (env.issueMap.value[key]?.length ?? 0) > 0
                    ? 'border-warning/20 bg-warning/5'
                    : 'border-default bg-default',
                ]"
              >
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="flex flex-wrap items-center gap-2">
                      <p class="text-sm font-medium text-default">
                        {{ env.fields.value[key]?.label || key }}
                      </p>
                      <Badge v-if="env.fields.value[key]?.required">
                        required
                      </Badge>
                      <Badge v-if="env.fields.value[key]?.secret" muted>
                        {{ env.fields.value[key]?.hasValue ? 'stored' : 'secret' }}
                      </Badge>
                    </div>
                    <p class="mt-1 text-xs text-muted">
                      {{ env.fields.value[key]?.description || 'No description available.' }}
                    </p>
                  </div>
                  <Badge muted>
                    {{ key }}
                  </Badge>
                </div>

                <div class="mt-3">
                  <!-- Boolean: 3-State-Pill (default / true / false) -->
                  <div
                    v-if="env.fields.value[key]?.type === 'boolean'"
                    class="flex items-center rounded-full border border-default bg-default p-1 w-fit"
                  >
                    <button
                      v-for="opt in [
                        { id: '', label: 'default' },
                        { id: 'true', label: 'true' },
                        { id: 'false', label: 'false' },
                      ]"
                      :key="opt.label"
                      type="button"
                      :class="[
                        'rounded-full px-3 py-1.5 text-[10px] font-mono uppercase tracking-[0.16em] transition-colors',
                        String(env.values.value[key] || '').toLowerCase() === opt.id
                          ? 'bg-primary text-inverted'
                          : 'text-muted hover:text-default',
                      ]"
                      @click="env.setFieldValue(key, opt.id)"
                    >
                      {{ opt.label }}
                    </button>
                  </div>

                  <!-- Enum: Select -->
                  <select
                    v-else-if="(env.fields.value[key]?.enum?.length ?? 0) > 0"
                    :value="env.values.value[key] || ''"
                    class="w-full rounded-xl border border-default bg-default px-3 py-2.5 text-sm text-default outline-none focus:border-primary/30"
                    @change="env.setFieldValue(key, ($event.target as HTMLSelectElement).value)"
                  >
                    <option value="">
                      Use default
                    </option>
                    <option
                      v-for="opt in env.fields.value[key]?.enum"
                      :key="opt"
                      :value="opt"
                    >
                      {{ opt }}
                    </option>
                  </select>

                  <!-- String / Integer -->
                  <div v-else class="flex items-center gap-2">
                    <input
                      :type="
                        env.fields.value[key]?.secret && !env.revealed.value[key]
                          ? 'password'
                          : env.fields.value[key]?.type === 'integer'
                            ? 'number'
                            : 'text'
                      "
                      :value="env.values.value[key] || ''"
                      :placeholder="secretPlaceholder(env.fields.value[key])"
                      autocomplete="off"
                      class="w-full rounded-xl border border-default bg-default px-3 py-2.5 text-sm text-default outline-none focus:border-primary/30"
                      @input="env.setFieldValue(key, ($event.target as HTMLInputElement).value)"
                    >
                    <button
                      v-if="env.fields.value[key]?.secret"
                      type="button"
                      :aria-label="env.revealed.value[key] ? 'Hide replacement value' : 'Reveal replacement value'"
                      class="rounded-xl border border-default bg-default p-2 text-muted transition-colors hover:text-default"
                      @click="env.toggleReveal(key)"
                    >
                      <UIcon
                        :name="env.revealed.value[key] ? 'i-lucide-eye-off' : 'i-lucide-eye'"
                        class="size-4"
                      />
                    </button>
                  </div>
                </div>

                <!-- Footer: Secret-Hint / Default / Issues -->
                <p
                  v-if="env.fields.value[key]?.secret"
                  class="mt-2 text-[11px] text-muted"
                >
                  {{
                    env.fields.value[key]?.hasValue
                      ? 'Leave blank to keep the stored secret. Enter a new value to replace it.'
                      : 'Enter a value to store this secret.'
                  }}
                </p>
                <p
                  v-else-if="env.fields.value[key]?.default !== undefined && env.fields.value[key]?.default !== null"
                  class="mt-2 text-[11px] text-muted"
                >
                  Default:
                  <span class="font-mono text-default">
                    {{ String(env.fields.value[key]?.default) }}
                  </span>
                </p>
                <p
                  v-for="(issue, index) in env.issueMap.value[key] || []"
                  :key="`${key}-issue-${index}`"
                  class="mt-1 text-[11px] text-warning/90"
                >
                  {{ issue }}
                </p>
              </div>
            </div>
          </div>
        </template>
        <div
          v-else
          class="rounded-xl border border-default bg-default px-4 py-6 text-sm text-muted"
        >
          No fields match the current filter.
        </div>
      </div>
    </div>
  </div>
</template>

