// Nuxt UI v3 Theme — entspricht dem Theme der React-Variante
// (siehe `dashboard/tailwind.config.js` + `index.css` Theme-Variablen).
// Theme-Flash-Vermeidung läuft über VueUse `useColorMode`
// (Standard von @nuxt/ui) — kein eigenes Inline-Skript mehr nötig.

export default defineAppConfig({
  ui: {
    colors: {
      primary: 'cyan',
      neutral: 'zinc',
    },
    button: {
      defaultVariants: {
        color: 'primary',
        size: 'md',
      },
    },
    card: {
      slots: {
        root: 'rounded-xl',
      },
    },
  },
})

