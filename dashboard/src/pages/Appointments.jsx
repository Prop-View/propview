import { Calendar, Clock, MapPin, User } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import useApi from '../hooks/useApi'

export default function Appointments() {
  const [filter, setFilter] = useState('all')

  const params = {}
  if (filter !== 'all') params.status = filter
  const { data, loading, error, refetch } = useApi(
    () => api.listAppointments({ limit: 100, ...params }),
    [filter]
  )

  const appointments = data?.items || []

  const upcoming = appointments.filter(
    (a) => a.status === 'scheduled' || a.status === 'confirmed'
  )
  const past = appointments.filter(
    (a) => a.status !== 'scheduled' && a.status !== 'confirmed'
  )

  function AppointmentCard({ apt }) {
    const d = new Date(apt.scheduled_at)
    return (
      <div className="bg-bg-card rounded-xl border border-border p-4 hover:border-border/80 transition-colors">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <Badge variant={apt.status} />
              {apt.confirmation_sms_sent_at && (
                <span className="text-[10px] text-accent font-medium">SMS sent</span>
              )}
            </div>
            <h3 className="text-[14px] font-semibold">{apt.lead_name || 'Unknown Lead'}</h3>
            {apt.property_address && (
              <div className="flex items-center gap-1.5 text-[12px] text-text-secondary mt-1.5">
                <MapPin size={12} />
                {apt.property_address}
              </div>
            )}
            {apt.agent_name && (
              <div className="flex items-center gap-1.5 text-[12px] text-text-secondary mt-1">
                <User size={12} />
                {apt.agent_name}
              </div>
            )}
          </div>
          <div className="text-right shrink-0">
            <div className="flex items-center gap-1.5 text-[13px] font-medium">
              <Calendar size={13} className="text-text-muted" />
              {d.toLocaleDateString([], { month: 'short', day: 'numeric' })}
            </div>
            <div className="flex items-center gap-1.5 text-[12px] text-text-muted mt-1 justify-end">
              <Clock size={12} />
              {d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5 max-w-[900px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Appointments</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          {data ? `${data.total} site visits scheduled by the AI agent` : 'Loading appointments...'}
        </p>
      </div>

      <div className="flex gap-1.5 flex-wrap">
        {['all', 'scheduled', 'confirmed', 'completed', 'no_show', 'cancelled'].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
              filter === f
                ? 'bg-text text-white'
                : 'bg-bg-card border border-border text-text-secondary hover:text-text'
            }`}
          >
            {f === 'all' ? 'All' : f === 'no_show' ? 'No Show' : f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : appointments.length === 0 ? (
        <EmptyState
          icon={Calendar}
          title="No appointments found"
          description={filter !== 'all' ? 'Try a different filter' : 'Appointments will appear as the AI agent books site visits.'}
        />
      ) : (
        <>
          {upcoming.length > 0 && (
            <div>
              <h2 className="text-[13px] font-semibold text-text-secondary uppercase tracking-wide mb-3">
                Upcoming ({upcoming.length})
              </h2>
              <div className="grid gap-3">
                {upcoming.map((a) => <AppointmentCard key={a.id} apt={a} />)}
              </div>
            </div>
          )}
          {past.length > 0 && (
            <div>
              <h2 className="text-[13px] font-semibold text-text-secondary uppercase tracking-wide mb-3">
                Past ({past.length})
              </h2>
              <div className="grid gap-3">
                {past.map((a) => <AppointmentCard key={a.id} apt={a} />)}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
