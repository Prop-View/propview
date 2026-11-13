import { Phone, Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import useApi from '../hooks/useApi'

function formatDuration(seconds) {
  if (!seconds) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export default function Calls() {
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')

  const params = {}
  if (filter !== 'all') params.outcome = filter
  const { data, loading, error, refetch } = useApi(
    () => api.listCalls({ limit: 100, ...params }),
    [filter]
  )

  const calls = (data?.items || []).filter(
    (c) =>
      !search ||
      c.caller_name?.toLowerCase().includes(search.toLowerCase()) ||
      c.caller_phone?.includes(search) ||
      c.call_id.includes(search)
  )

  return (
    <div className="space-y-5 max-w-[1200px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Calls</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          All incoming calls handled by the AI agent
          {data && ` (${data.total} total)`}
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            placeholder="Search by name, number, or call ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-bg-card text-[13px] outline-none focus:border-accent transition-colors"
          />
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {['all', 'booked', 'qualified', 'transferred', 'nurture', 'dropped'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
                filter === f
                  ? 'bg-text text-white'
                  : 'bg-bg-card border border-border text-text-secondary hover:text-text'
              }`}
            >
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : calls.length === 0 ? (
        <EmptyState icon={Phone} title="No calls found" description={filter !== 'all' || search ? 'Try adjusting your filters' : 'Calls will appear here once the AI agent handles its first call.'} />
      ) : (
        <div className="bg-bg-card rounded-xl border border-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-border text-text-muted text-[11px] uppercase tracking-wider">
                  <th className="text-left px-5 py-3 font-medium">Caller</th>
                  <th className="text-left px-5 py-3 font-medium">Duration</th>
                  <th className="text-left px-5 py-3 font-medium">Outcome</th>
                  <th className="text-left px-5 py-3 font-medium">Turns</th>
                  <th className="text-left px-5 py-3 font-medium">Tools</th>
                  <th className="text-left px-5 py-3 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => (
                  <tr key={call.call_id || call.id} className="border-b border-border-light hover:bg-bg-hover transition-colors">
                    <td className="px-5 py-3.5">
                      <Link to={`/calls/${call.call_id}`} className="hover:text-accent">
                        <div className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-full bg-border-light flex items-center justify-center">
                            <Phone size={14} className="text-text-muted" />
                          </div>
                          <div>
                            <div className="font-medium">{call.caller_name || 'Unknown Caller'}</div>
                            <div className="text-[11px] text-text-muted">{call.caller_phone || call.call_id}</div>
                          </div>
                        </div>
                      </Link>
                    </td>
                    <td className="px-5 py-3.5 text-text-secondary">{formatDuration(call.duration_seconds)}</td>
                    <td className="px-5 py-3.5"><Badge variant={call.analytics_outcome || call.outcome} /></td>
                    <td className="px-5 py-3.5 text-text-muted">{call.total_turns || '—'}</td>
                    <td className="px-5 py-3.5">
                      {call.tools_used && JSON.parse(call.tools_used || '[]').length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {JSON.parse(call.tools_used).map((t) => (
                            <span key={t} className="px-1.5 py-0.5 rounded bg-border-light text-[10px] text-text-muted font-mono">
                              {t}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-text-muted">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3.5 text-text-muted text-[12px] whitespace-nowrap">
                      {new Date(call.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
