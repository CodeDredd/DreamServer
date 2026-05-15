// Nuxt UI v4 Theme — entspricht dem Theme der React-Variante
// (siehe `dashboard/tailwind.config.js` + `index.css` Theme-Variablen).
// Theme-Flash-Vermeidung laeuft ueber VueUse `useColorMode` (Standard
// von @nuxt/ui) — kein eigenes Inline-Skript mehr noetig.
//
// Slot-Overrides folgen dem Pattern aus dem Referenz-Projekt
// (futtertieraerztin/website/app.config.ts): Theme-Tokens werden hier
// zentral parametriert, einzelne Komponenten bekommen Slot-Overrides
// statt verstreuter Tailwind-Klassen in den Templates.

export default defineAppConfig({
  ui: {
    colors: {
      primary: 'cyan',
      neutral: 'zinc',
      secondary: 'violet',
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
    pageCard: {
      slots: {
        wrapper: 'flex flex-col gap-4 flex-1 items-stretch',
      },
    },
    dashboardSidebar: {
      slots: {
        root: 'bg-elevated/40',
        header: 'border-b border-default',
        footer: 'border-t border-default',
      },
    },
    navigationMenu: {
      slots: {
        root: 'gap-1',
        link: 'rounded-lg',
      },
    },
    select: {
      slots: {
        content: 'min-w-fit',
      },
    },
  },
})

