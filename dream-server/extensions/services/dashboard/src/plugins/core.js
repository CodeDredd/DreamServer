import { lazy } from 'react'
import {
  LayoutDashboard,
  Settings,
  Puzzle,
  Activity,
  Box,
  ListChecks,
  Network,
  UserPlus,
  TrendingUp,
  GitBranch,
} from 'lucide-react'

const Dashboard = lazy(() => import('../pages/Dashboard'))
const SettingsPage = lazy(() => import('../pages/Settings'))
const Extensions = lazy(() => import('../pages/Extensions'))
const GPUMonitor = lazy(() => import('../pages/GPUMonitor'))
const Models = lazy(() => import('../pages/Models'))
const Projects = lazy(() => import('../pages/Projects'))
const ServiceMap = lazy(() => import('../pages/ServiceMap'))
const Invites = lazy(() => import('../pages/Invites'))
const FinanceGuru = lazy(() => import('../pages/FinanceGuru'))
const RepoProjectMap = lazy(() => import('../pages/RepoProjectMap'))

export const coreRoutes = [
  {
    id: 'dashboard',
    path: '/',
    label: 'Dashboard',
    icon: LayoutDashboard,
    component: Dashboard,
    getProps: ({ status, loading }) => ({ status, loading }),
    sidebar: true,
    order: 0,
  },
  {
    id: 'gpu-monitor',
    path: '/gpu',
    label: 'GPU Monitor',
    icon: Activity,
    component: GPUMonitor,
    getProps: () => ({}),
    // Route is always registered; sidebar entry only appears on multi-GPU systems
    sidebar: ({ status }) => (status?.gpu?.gpu_count || 1) > 1,
    order: 1,
  },
  {
    id: 'extensions',
    path: '/extensions',
    label: 'Extensions',
    icon: Puzzle,
    component: Extensions,
    getProps: () => ({}),
    sidebar: true,
    order: 2,
  },
  {
    id: 'integrations',
    path: '/extensions/integrations',
    label: 'Integrations',
    icon: Network,
    component: ServiceMap,
    getProps: () => ({}),
    sidebar: true,
    order: 2.1,
  },
  {
    id: 'models',
    path: '/models',
    label: 'Models',
    icon: Box,
    component: Models,
    getProps: () => ({}),
    sidebar: true,
    order: 3,
  },
  {
    id: 'projects',
    path: '/projects',
    label: 'Projects',
    icon: ListChecks,
    component: Projects,
    getProps: () => ({}),
    // Sidebar entry only appears once Vikunja is registered as a service.
    // Route is always reachable so first-time setup pages still render.
    sidebar: ({ status }) =>
      (status?.services || []).some((s) =>
        (s.name || '').toLowerCase().includes('vikunja')
      ),
  },
  {
    id: 'invites',
    path: '/invites',
    label: 'Invites',
    icon: UserPlus,
    component: Invites,
    getProps: () => ({}),
    sidebar: true,
    order: 4,
  },
  {
    // Finance Guru — paper-trade strategy engine. Sidebar entry only
    // appears when the upstream finance-guru-api service is registered
    // in the dashboard's service inventory; route stays reachable so
    // first-time setup can land here directly via URL.
    // See AGENT-OPERATIONS.md §11.
    id: 'finance-guru',
    path: '/finance-guru',
    label: 'Finance Guru',
    icon: TrendingUp,
    component: FinanceGuru,
    getProps: () => ({}),
    sidebar: ({ status }) =>
      (status?.services || []).some((s) =>
        (s.name || '').toLowerCase().includes('finance-guru')
      ),
    order: 4.5,
  },
  {
    id: 'repo-map',
    path: '/repo-map',
    label: 'Repo → Project Map',
    icon: GitBranch,
    component: RepoProjectMap,
    getProps: () => ({}),
    // Only show in sidebar when both Vikunja and n8n are present —
    // the map is useless without both.
    sidebar: ({ status }) => {
      const services = status?.services || []
      const has = (needle) =>
        services.some((s) => (s.name || '').toLowerCase().includes(needle))
      return has('vikunja') && has('n8n')
    },
    order: 5,
  },
  {
    id: 'settings',
    path: '/settings',
    label: 'Settings',
    icon: Settings,
    component: SettingsPage,
    getProps: () => ({}),
    sidebar: true,
    order: 99,
  },
]

export const coreExternalLinks = []
