<!--
  Color-Mode-Toggle. Eigene Komponente weil Nuxt UI v4 keinen
  Out-of-the-Box Toggle mehr exportiert; nutzt useColorMode().
-->
<script setup lang="ts">
const colorMode = useColorMode()

const isDark = computed({
  get: () => colorMode.value === 'dark',
  set: (v: boolean) => {
    colorMode.preference = v ? 'dark' : 'light'
  },
})
</script>

<template>
  <UButton
    :icon="isDark ? 'i-lucide-moon' : 'i-lucide-sun'"
    color="neutral"
    variant="ghost"
    size="sm"
    square
    :aria-label="isDark ? 'Light Mode' : 'Dark Mode'"
    @click="isDark = !isDark"
  />
</template>

