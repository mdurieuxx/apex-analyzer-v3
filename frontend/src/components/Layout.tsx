import { NavLink } from 'react-router-dom'
import { Activity, GitFork, BarChart2, Settings, Wifi, WifiOff } from 'lucide-react'
import clsx from 'clsx'
import type { LiveState } from '../hooks/useWebSocket'

interface Props {
  live: LiveState
  children: React.ReactNode
}

export function Layout({ live, children }: Props) {
  const nav = [
    { to: '/',            icon: Activity,  label: 'Live Timing' },
    { to: '/pits',        icon: GitFork,   label: 'Stands'      },
    { to: '/performance', icon: BarChart2, label: 'Performance' },
    { to: '/settings',    icon: Settings,  label: 'Config'      },
  ]

  const countdown = live.countdown
  const mm = Math.floor(countdown / 60)
  const ss = String(countdown % 60).padStart(2, '0')

  return (
    <div className="min-h-screen flex flex-col bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center gap-4">
        <div className="flex-1">
          <h1 className="text-lg font-bold text-white leading-none">
            {live.title1 || 'Karting Live'}
          </h1>
          {live.title2 && (
            <p className="text-sm text-gray-400 mt-0.5">{live.title2}</p>
          )}
        </div>

        {countdown > 0 && (
          <div className="text-2xl font-mono font-bold text-yellow-400">
            {mm}:{ss}
          </div>
        )}

        <div className="flex items-center gap-2 text-sm">
          {live.connected ? (
            <span className="flex items-center gap-1 text-green-400">
              <Wifi size={16} /> Apex
            </span>
          ) : (
            <span className="flex items-center gap-1 text-red-400">
              <WifiOff size={16} /> Déconnecté
            </span>
          )}
          {live.wsConnected ? (
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" title="WebSocket OK" />
          ) : (
            <span className="w-2 h-2 rounded-full bg-yellow-400" title="Reconnexion..." />
          )}
        </div>
      </header>

      {/* Nav */}
      <nav className="bg-gray-900 border-b border-gray-800 flex">
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                isActive
                  ? 'border-orange-500 text-orange-400'
                  : 'border-transparent text-gray-400 hover:text-white'
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Content */}
      <main className="flex-1 overflow-auto p-4">{children}</main>
    </div>
  )
}
