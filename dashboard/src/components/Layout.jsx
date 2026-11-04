import {
  BarChart3,
  Building2,
  Calendar,
  Home,
  LogOut,
  Menu,
  Phone,
  Settings,
  Users,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api, getAuth } from '../api'

const nav = [
  { to: '/', icon: Home, label: 'Dashboard' },
  { to: '/calls', icon: Phone, label: 'Calls' },
  { to: '/leads', icon: Users, label: 'Leads' },
  { to: '/properties', icon: Building2, label: 'Properties' },
  { to: '/appointments', icon: Calendar, label: 'Appointments' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/settings', icon: Settings, label: 'Settings' },
]

export default function Layout({ onLogout }) {
  const [open, setOpen] = useState(false)
  const [branding, setBranding] = useState(null)
  const [apiHealthy, setApiHealthy] = useState(null)
  const { tenantId } = getAuth()

  useEffect(() => {
    api.getBranding().then(setBranding).catch(() => {})
    api.health().then(() => setApiHealthy(true)).catch(() => setApiHealthy(false))
  }, [])

  const agencyName = branding?.agency_name || tenantId

  return (
    <div className="flex h-screen overflow-hidden">
      {open && (
        <div
          className="fixed inset-0 bg-black/40 z-30 lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      <aside
        className={`
          fixed lg:static inset-y-0 left-0 z-40 w-[220px] bg-bg-sidebar flex flex-col
          transition-transform duration-200 lg:translate-x-0
          ${open ? 'translate-x-0' : '-translate-x-full'}
        `}
      >
        <div className="flex items-center gap-2.5 px-5 h-16 border-b border-white/[0.06]">
          <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
            <Building2 size={16} className="text-white" />
          </div>
          <span className="text-[15px] font-semibold text-white tracking-[-0.01em]">
            Propview
          </span>
          <button
            className="ml-auto lg:hidden text-text-sidebar-muted hover:text-white"
            onClick={() => setOpen(false)}
          >
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 py-3 px-2.5 space-y-0.5 overflow-y-auto">
          {nav.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-[13px] font-medium transition-colors
                ${
                  isActive
                    ? 'bg-white/[0.08] text-white'
                    : 'text-text-sidebar-muted hover:text-text-sidebar hover:bg-white/[0.04]'
                }`
              }
            >
              <Icon size={16} strokeWidth={1.75} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="px-4 py-4 border-t border-white/[0.06]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-accent/20 flex items-center justify-center text-[11px] font-semibold text-accent">
              {agencyName.slice(0, 2).toUpperCase()}
            </div>
            <div className="text-[12px] flex-1 min-w-0">
              <div className="text-text-sidebar font-medium truncate">{agencyName}</div>
              <div className="text-text-sidebar-muted truncate">{tenantId}</div>
            </div>
            <button
              onClick={onLogout}
              className="text-text-sidebar-muted hover:text-white transition-colors"
              title="Sign out"
            >
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 flex items-center px-4 lg:px-6 border-b border-border bg-bg-card">
          <button
            className="lg:hidden mr-3 text-text-secondary hover:text-text"
            onClick={() => setOpen(true)}
          >
            <Menu size={20} />
          </button>
          <div className="flex-1" />
          <div className="flex items-center gap-3">
            {apiHealthy !== null && (
              <div
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-semibold ${
                  apiHealthy
                    ? 'bg-accent-light text-accent'
                    : 'bg-red-50 text-hot'
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    apiHealthy ? 'bg-accent animate-pulse' : 'bg-hot'
                  }`}
                />
                {apiHealthy ? 'API Connected' : 'API Offline'}
              </div>
            )}
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
