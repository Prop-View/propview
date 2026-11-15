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
    const [scheduledAt, setScheduledAt] = useState(() => {
      const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      return local.toISOString().slice(0, 16)
    })
    const [busy, setBusy] = useState(false)
    const [message, setMessage] = useState('')

    async function saveReschedule() {
      setBusy(true)
      setMessage('')
      try {
        await api.updateAppointment(apt.id, { scheduled_at: new Date(scheduledAt).toISOString() })
        setMessage('Appointment rescheduled.')
        refetch()
      } catch (requestError) {
        setMessage(`Could not reschedule: ${requestError.message}`)
      } finally {
        setBusy(false)
      }
    }

    async function cancel() {
      if (!window.confirm('Cancel this appointment?')) return
      setBusy(true)
      setMessage('')
      try {
        await api.cancelAppointment(apt.id)
        setMessage('Appointment cancelled.')
        refetch()
      } catch (requestError) {
        setMessage(`Could not cancel: ${requestError.message}`)
      } finally {
        setBusy(false)
      }
    }

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
        {(apt.status === 'scheduled' || apt.status === 'confirmed') && (
          <div className="mt-4 pt-3 border-t border-border-light flex flex-col sm:flex-row sm:items-end gap-3">
            <label className="flex-1">
              <span className="text-[11px] text-text-muted block mb-1">Reschedule to</span>
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={(event) => setScheduledAt(event.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-border bg-bg-card text-[12px]"
              />
            </label>
            <button type="button" disabled={busy || !scheduledAt} onClick={saveReschedule} className="px-3 py-2 rounded-lg bg-accent text-white text-[12px] disabled:opacity-50">
              {busy ? 'Saving...' : 'Reschedule'}
            </button>
            <button type="button" disabled={busy} onClick={cancel} className="px-3 py-2 rounded-lg border border-border text-hot text-[12px] disabled:opacity-50">
              Cancel appointment
            </button>
          </div>
        )}
        {message && <p role="status" className={`mt-2 text-[11px] ${message.startsWith('Could not') ? 'text-hot' : 'text-accent'}`}>{message}</p>}
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
