import {
  ArrowUpRight,
  Calendar,
  Clock,
  Flame,
  Phone,
  TrendingUp,
  Users,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import StatCard from '../components/StatCard'
import useApi from '../hooks/useApi'

const PRIORITY_COLORS = { high: '#ef4444', medium: '#f59e0b', low: '#3b82f6' }

function formatDuration(seconds) {
  if (!seconds) return '0s'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export default function Dashboard() {
  const { data: stats, loading, error, refetch } = useApi(() => api.getStats(), [])
  const { data: callsData } = useApi(() => api.listCalls({ limit: 5 }), [])

  if (loading) return <Loading />
  if (error) return <ErrorState message={error} onRetry={refetch} />
  if (!stats) return null

  const dailyData = stats.daily_calls.map((d) => {
    const booking = stats.daily_bookings.find((b) => b.date === d.date)
    return { date: d.date.slice(5), calls: d.calls, booked: booking?.booked || 0 }
  })

  const priorityData = Object.entries(stats.lead_priority_counts).map(([name, value]) => ({
    name: name.charAt(0).toUpperCase() + name.slice(1),
    value,
    color: PRIORITY_COLORS[name] || '#a8a29e',
  }))

  const calls = callsData?.items || []

  return (
    <div className="space-y-6 max-w-[1200px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Dashboard</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          Real-time overview of your AI voice agent
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard
          icon={Phone} label="Calls Today" accent
          value={stats.calls_today}
          sub={`${stats.total_calls.toLocaleString()} total`}
        />
        <StatCard
          icon={Clock} label="Avg Duration"
          value={formatDuration(stats.avg_duration_seconds)}
        />
        <StatCard
          icon={TrendingUp} label="Conversion" accent
          value={`${stats.conversion_rate}%`}
          sub="Calls → Bookings"
        />
        <StatCard
          icon={Flame} label="Hot Leads"
          value={stats.hot_leads}
          sub={`${stats.active_leads} active total`}
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 bg-bg-card rounded-xl border border-border p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[14px] font-semibold">Call Volume</h2>
            <span className="text-[12px] text-text-muted">Last 7 days</span>
          </div>
          {dailyData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={dailyData}>
                <defs>
                  <linearGradient id="callGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#16a34a" stopOpacity={0.12} />
                    <stop offset="100%" stopColor="#16a34a" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="bookedGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.12} />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 12, fill: '#a8a29e' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 12, fill: '#a8a29e' }} axisLine={false} tickLine={false} width={30} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e7e5e4', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }} />
                <Area type="monotone" dataKey="calls" stroke="#16a34a" fill="url(#callGrad)" strokeWidth={2} name="Total Calls" />
                <Area type="monotone" dataKey="booked" stroke="#3b82f6" fill="url(#bookedGrad)" strokeWidth={2} name="Booked" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={Phone} title="No call data yet" description="Calls will appear here once the AI agent handles its first call." />
          )}
        </div>

        <div className="bg-bg-card rounded-xl border border-border p-5">
          <h2 className="text-[14px] font-semibold mb-3">Lead Priority</h2>
          {priorityData.length > 0 ? (
            <>
              <div className="flex justify-center">
                <ResponsiveContainer width={180} height={180}>
                  <PieChart>
                    <Pie
                      data={priorityData}
                      cx="50%" cy="50%"
                      innerRadius={55} outerRadius={80}
                      paddingAngle={3} dataKey="value" strokeWidth={0}
                    >
                      {priorityData.map((entry) => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e7e5e4' }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex justify-center gap-4 mt-2">
                {priorityData.map((item) => (
                  <div key={item.name} className="flex items-center gap-1.5 text-[12px] text-text-secondary">
                    <span className="w-2 h-2 rounded-full" style={{ background: item.color }} />
                    {item.name} ({item.value})
                  </div>
                ))}
              </div>
            </>
          ) : (
            <EmptyState icon={Users} title="No leads yet" />
          )}
        </div>
      </div>

      <div className="bg-bg-card rounded-xl border border-border">
        <div className="flex items-center justify-between p-5 pb-0">
          <h2 className="text-[14px] font-semibold">Recent Calls</h2>
          <Link
            to="/calls"
            className="text-[12px] text-accent hover:text-accent-hover font-medium flex items-center gap-0.5"
          >
            View all <ArrowUpRight size={13} />
          </Link>
        </div>
        {calls.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-border text-text-muted text-[11px] uppercase tracking-wider">
                  <th className="text-left px-5 py-3 font-medium">Caller</th>
                  <th className="text-left px-5 py-3 font-medium">Duration</th>
                  <th className="text-left px-5 py-3 font-medium">Outcome</th>
                  <th className="text-left px-5 py-3 font-medium">Turns</th>
                  <th className="text-left px-5 py-3 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => (
                  <tr key={call.call_id} className="border-b border-border-light hover:bg-bg-hover transition-colors">
                    <td className="px-5 py-3">
                      <Link to={`/calls/${call.call_id}`} className="hover:text-accent">
                        <div className="font-medium">{call.caller_name || 'Unknown'}</div>
                        <div className="text-[11px] text-text-muted">{call.caller_phone || call.call_id}</div>
                      </Link>
                    </td>
                    <td className="px-5 py-3 text-text-secondary">
                      {formatDuration(call.duration_seconds)}
                    </td>
                    <td className="px-5 py-3">
                      <Badge variant={call.analytics_outcome || call.outcome} />
                    </td>
                    <td className="px-5 py-3 text-text-muted">{call.total_turns || '—'}</td>
                    <td className="px-5 py-3 text-text-muted text-[12px]">
                      {new Date(call.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={Phone} title="No calls yet" description="Incoming calls will appear here." />
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="bg-bg-card rounded-xl border border-border p-5">
          <h2 className="text-[14px] font-semibold mb-3">Quick Stats</h2>
          <div className="space-y-3">
            {[
              { icon: Users, label: 'Active Leads', value: stats.active_leads },
              { icon: Calendar, label: 'Appointments This Week', value: stats.appointments_this_week },
              { icon: Phone, label: 'Total Calls', value: stats.total_calls.toLocaleString() },
            ].map((item) => (
              <div key={item.label} className="flex items-center justify-between py-2 border-b border-border-light last:border-0">
                <div className="flex items-center gap-2.5 text-[13px] text-text-secondary">
                  <item.icon size={15} strokeWidth={1.75} />
                  {item.label}
                </div>
                <span className="text-[14px] font-semibold">{item.value}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-bg-card rounded-xl border border-border p-5">
          <h2 className="text-[14px] font-semibold mb-3">AI Tools Usage</h2>
          {stats.tool_usage.length > 0 ? (
            <div className="space-y-2.5">
              {stats.tool_usage.map((tool) => {
                const maxCount = stats.tool_usage[0]?.count || 1
                const pct = Math.round((tool.count / maxCount) * 100)
                return (
                  <div key={tool.tool_name} className="space-y-1">
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="text-text-secondary font-mono">{tool.tool_name}</span>
                      <span className="text-text-muted">{tool.count}</span>
                    </div>
                    <div className="h-1.5 bg-border-light rounded-full overflow-hidden">
                      <div className="h-full bg-accent/60 rounded-full transition-all" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <EmptyState title="No tool data yet" />
          )}
        </div>
      </div>
    </div>
  )
}
