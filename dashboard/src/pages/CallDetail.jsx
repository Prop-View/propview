import { ArrowLeft, Bot, Clock, Phone, User, Wrench } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
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

export default function CallDetail() {
  const { callId } = useParams()
  const { data, loading, error, refetch } = useApi(
    () => api.getCallDetail(callId),
    [callId]
  )

  if (loading) return <Loading />
  if (error) return <ErrorState message={error} onRetry={refetch} />
  if (!data) return null

  const { interaction, turns, tool_invocations, analytics } = data

  return (
    <div className="space-y-5 max-w-[900px]">
      <Link
        to="/calls"
        className="inline-flex items-center gap-1.5 text-[13px] text-text-secondary hover:text-text transition-colors"
      >
        <ArrowLeft size={14} /> Back to calls
      </Link>

      <div className="bg-bg-card rounded-xl border border-border p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.02em]">
              {interaction.caller_name || 'Unknown Caller'}
            </h1>
            <p className="text-[13px] text-text-muted mt-0.5">
              {interaction.caller_phone || interaction.call_id}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={analytics?.outcome || interaction.outcome} />
            <span className="text-[12px] text-text-muted font-mono">{interaction.call_id}</span>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5 pt-5 border-t border-border-light">
          <div>
            <div className="text-[11px] text-text-muted uppercase tracking-wide mb-1">Duration</div>
            <div className="flex items-center gap-1.5 text-[14px] font-medium">
              <Clock size={14} className="text-text-muted" />
              {formatDuration(interaction.duration_seconds)}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-text-muted uppercase tracking-wide mb-1">Time</div>
            <div className="text-[14px] font-medium">
              {new Date(interaction.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-text-muted uppercase tracking-wide mb-1">Turns</div>
            <div className="text-[14px] font-medium">{analytics?.total_turns || turns.length || '—'}</div>
          </div>
          <div>
            <div className="text-[11px] text-text-muted uppercase tracking-wide mb-1">Barge-ins</div>
            <div className="text-[14px] font-medium">{analytics?.barge_in_count ?? '—'}</div>
          </div>
        </div>
      </div>

      {tool_invocations.length > 0 && (
        <div className="bg-bg-card rounded-xl border border-border p-5">
          <h2 className="text-[14px] font-semibold mb-3 flex items-center gap-2">
            <Wrench size={15} /> Tools Invoked ({tool_invocations.length})
          </h2>
          <div className="space-y-2">
            {tool_invocations.map((t) => (
              <div key={t.id} className="flex items-center justify-between py-2 border-b border-border-light last:border-0">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded-lg bg-accent/5 border border-accent/10 text-[12px] font-mono text-accent">
                    {t.tool_name}
                  </span>
                  {!t.success && (
                    <span className="text-[11px] text-hot font-medium">Failed</span>
                  )}
                </div>
                {t.latency_ms != null && (
                  <span className="text-[11px] text-text-muted">{Math.round(t.latency_ms)}ms</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-bg-card rounded-xl border border-border p-5">
        <h2 className="text-[14px] font-semibold mb-4">Transcript</h2>
        {turns.length > 0 ? (
          <div className="space-y-3">
            {turns.map((turn) => (
              <div
                key={turn.id}
                className={`flex gap-3 ${turn.speaker === 'agent' ? '' : 'flex-row-reverse'}`}
              >
                <div
                  className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
                    turn.speaker === 'agent'
                      ? 'bg-accent/10 text-accent'
                      : 'bg-border-light text-text-muted'
                  }`}
                >
                  {turn.speaker === 'agent' ? <Bot size={14} /> : <User size={14} />}
                </div>
                <div
                  className={`max-w-[80%] px-3.5 py-2.5 rounded-2xl text-[13px] leading-relaxed ${
                    turn.speaker === 'agent'
                      ? 'bg-border-light text-text rounded-tl-md'
                      : 'bg-accent text-white rounded-tr-md'
                  }`}
                >
                  {turn.text}
                  {turn.interrupted && (
                    <span className="text-[10px] opacity-60 ml-1">[interrupted]</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : interaction.transcript ? (
          <pre className="text-[13px] text-text-secondary whitespace-pre-wrap leading-relaxed">
            {interaction.transcript}
          </pre>
        ) : (
          <EmptyState icon={Phone} title="No transcript available" />
        )}
      </div>
    </div>
  )
}
