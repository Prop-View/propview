import { BarChart3 } from 'lucide-react'
import {
  Bar,
  BarChart,
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
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import useApi from '../hooks/useApi'

const OUTCOME_COLORS = {
  booked: '#16a34a',
  qualified: '#8b5cf6',
  nurture: '#3b82f6',
  transferred: '#f59e0b',
  dropped: '#a8a29e',
  unknown: '#d4d4d4',
}

function formatDuration(seconds) {
  if (!seconds) return '0s'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export default function Analytics() {
  const { data: stats, loading, error, refetch } = useApi(() => api.getStats(), [])

  if (loading) return <Loading />
  if (error) return <ErrorState message={error} onRetry={refetch} />
  if (!stats) return null

  const outcomeData = Object.entries(stats.outcome_counts).map(([name, value]) => ({
    name: name.charAt(0).toUpperCase() + name.slice(1),
    value,
    color: OUTCOME_COLORS[name] || '#a8a29e',
  }))

  const dailyData = stats.daily_calls.map((d) => {
    const booking = stats.daily_bookings.find((b) => b.date === d.date)
    return { date: d.date.slice(5), calls: d.calls, booked: booking?.booked || 0 }
  })

  const toolData = stats.tool_usage.map((t) => ({
    name: t.tool_name.length > 18 ? t.tool_name.slice(0, 16) + '...' : t.tool_name,
    full_name: t.tool_name,
    count: t.count,
  }))

  return (
    <div className="space-y-6 max-w-[1200px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Analytics</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          Performance metrics and conversion analysis
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: 'Total Calls', value: stats.total_calls.toLocaleString() },
          { label: 'Avg Duration', value: formatDuration(stats.avg_duration_seconds) },
          { label: 'Conversion Rate', value: `${stats.conversion_rate}%` },
          { label: 'Active Leads', value: stats.active_leads },
        ].map((m) => (
          <div key={m.label} className="bg-bg-card rounded-xl border border-border p-4">
            <div className="text-[11px] text-text-muted uppercase tracking-wide">{m.label}</div>
            <div className="text-[22px] font-semibold mt-1">{m.value}</div>
          </div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="bg-bg-card rounded-xl border border-border p-5">
          <h2 className="text-[14px] font-semibold mb-4">Daily Call Volume</h2>
          {dailyData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={dailyData} barGap={2}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 12, fill: '#a8a29e' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 12, fill: '#a8a29e' }} axisLine={false} tickLine={false} width={30} />
                <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e7e5e4' }} />
                <Bar dataKey="calls" fill="#16a34a" radius={[4, 4, 0, 0]} name="Total" opacity={0.2} />
                <Bar dataKey="booked" fill="#16a34a" radius={[4, 4, 0, 0]} name="Booked" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState icon={BarChart3} title="No call data yet" />
          )}
        </div>

        <div className="bg-bg-card rounded-xl border border-border p-5">
          <h2 className="text-[14px] font-semibold mb-4">Outcome Distribution</h2>
          {outcomeData.length > 0 ? (
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={180} height={180}>
                <PieChart>
                  <Pie
                    data={outcomeData}
                    cx="50%" cy="50%"
                    innerRadius={55} outerRadius={80}
                    paddingAngle={3} dataKey="value" strokeWidth={0}
                  >
                    {outcomeData.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e7e5e4' }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2">
                {outcomeData.map((item) => (
                  <div key={item.name} className="flex items-center gap-2 text-[12px]">
                    <span className="w-2.5 h-2.5 rounded-sm" style={{ background: item.color }} />
                    <span className="text-text-secondary">{item.name}</span>
                    <span className="font-semibold ml-auto">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <EmptyState icon={BarChart3} title="No outcome data yet" />
          )}
        </div>
      </div>

      <div className="bg-bg-card rounded-xl border border-border p-5">
        <h2 className="text-[14px] font-semibold mb-4">Tool Usage</h2>
        {toolData.length > 0 ? (
          <ResponsiveContainer width="100%" height={Math.max(200, toolData.length * 40)}>
            <BarChart data={toolData} layout="vertical" barGap={2}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e7e5e4" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11, fill: '#a8a29e' }} axisLine={false} tickLine={false} />
              <YAxis
                type="category" dataKey="name"
                tick={{ fontSize: 11, fill: '#a8a29e' }}
                axisLine={false} tickLine={false} width={140}
              />
              <Tooltip
                contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e7e5e4' }}
                formatter={(value, _, props) => [value, props.payload.full_name]}
              />
              <Bar dataKey="count" fill="#16a34a" radius={[0, 4, 4, 0]} name="Invocations" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <EmptyState icon={BarChart3} title="No tool usage data yet" />
        )}
      </div>
    </div>
  )
}
