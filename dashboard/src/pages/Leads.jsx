import { ArrowUpDown, Search, Users } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import useApi from '../hooks/useApi'

function formatBudget(min, max) {
  if (!min && !max) return '—'
  const fmt = (n) => {
    if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`
    return `$${n}`
  }
  if (min && max) return `${fmt(min)}–${fmt(max)}`
  if (min) return `${fmt(min)}+`
  return `Up to ${fmt(max)}`
}

export default function Leads() {
  const [search, setSearch] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('all')

  const params = {}
  if (priorityFilter !== 'all') params.priority = priorityFilter
  const { data, loading, error, refetch } = useApi(
    () => api.listLeads({ limit: 100, ...params }),
    [priorityFilter]
  )

  const leads = (data?.items || []).filter(
    (l) =>
      !search ||
      l.full_name?.toLowerCase().includes(search.toLowerCase()) ||
      l.phone_number?.includes(search)
  )

  return (
    <div className="space-y-5 max-w-[1200px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Leads</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          {data ? `${data.total} leads captured by AI agent` : 'Loading leads...'}
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            placeholder="Search leads..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-bg-card text-[13px] outline-none focus:border-accent transition-colors"
          />
        </div>
        <div className="flex gap-1.5">
          {['all', 'high', 'medium', 'low'].map((p) => (
            <button
              key={p}
              onClick={() => setPriorityFilter(p)}
              className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
                priorityFilter === p
                  ? 'bg-text text-white'
                  : 'bg-bg-card border border-border text-text-secondary hover:text-text'
              }`}
            >
              {p === 'all' ? 'All' : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : leads.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No leads found"
          description={search || priorityFilter !== 'all' ? 'Try adjusting your filters' : 'Leads will appear as the AI agent qualifies callers.'}
        />
      ) : (
        <div className="grid gap-3">
          {leads.map((lead) => (
            <div
              key={lead.id}
              className="bg-bg-card rounded-xl border border-border p-4 hover:border-border/80 transition-colors"
            >
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  <div className="w-10 h-10 rounded-full bg-border-light flex items-center justify-center shrink-0">
                    <Users size={16} className="text-text-muted" />
                  </div>
                  <div className="min-w-0">
                    <div className="font-medium text-[14px]">{lead.full_name || 'Unknown'}</div>
                    <div className="text-[12px] text-text-muted">{lead.phone_number}</div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-4 text-[12px]">
                  <div className="space-y-0.5">
                    <div className="text-text-muted text-[10px] uppercase tracking-wide">Intent</div>
                    <div className="text-text-secondary font-medium capitalize">{lead.intent || '—'}</div>
                  </div>
                  <div className="space-y-0.5">
                    <div className="text-text-muted text-[10px] uppercase tracking-wide">Budget</div>
                    <div className="text-text-secondary font-medium">{formatBudget(lead.budget_min, lead.budget_max)}</div>
                  </div>
                  <div className="space-y-0.5">
                    <div className="text-text-muted text-[10px] uppercase tracking-wide">Timeline</div>
                    <div className="text-text-secondary font-medium capitalize">{lead.timeline || '—'}</div>
                  </div>
                  <div className="space-y-0.5">
                    <div className="text-text-muted text-[10px] uppercase tracking-wide">Updated</div>
                    <div className="text-text-secondary font-medium">
                      {new Date(lead.updated_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                    </div>
                  </div>
                  <div className="flex gap-1.5">
                    <Badge variant={lead.priority} />
                    <Badge variant={lead.status} />
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
