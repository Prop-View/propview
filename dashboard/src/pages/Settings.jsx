import {
  Building2,
  CalendarDays,
  FileText,
  Globe,
  Phone,
  Shield,
  Users,
  Volume2,
  Webhook,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, getAuth } from '../api'

const fieldClass = 'w-full px-3 py-2 rounded-lg border border-border bg-bg-card text-[13px] outline-none focus:border-accent transition-colors'
const labelClass = 'text-[12px] text-text-secondary font-medium block mb-1.5'

function Section({ icon: Icon, title, description, children }) {
  return (
    <section className="bg-bg-card rounded-xl border border-border p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-9 h-9 rounded-lg bg-border-light flex items-center justify-center shrink-0">
          <Icon size={17} className="text-text-secondary" />
        </div>
        <div>
          <h2 className="text-[14px] font-semibold">{title}</h2>
          <p className="text-[12px] text-text-muted mt-0.5">{description}</p>
        </div>
      </div>
      {children}
    </section>
  )
}

function Field({ label, value, onChange, type = 'text', ...props }) {
  return (
    <label>
      <span className={labelClass}>{label}</span>
      <input className={fieldClass} type={type} value={value ?? ''} onChange={(event) => onChange(event.target.value)} {...props} />
    </label>
  )
}

export default function Settings() {
  const { tenantId, user } = getAuth()
  const canManage = user?.role === 'owner'
  const [branding, setBranding] = useState(null)
  const [settings, setSettings] = useState(null)
  const [health, setHealth] = useState(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    Promise.all([api.getBranding(), api.getSettings(), api.health()])
      .then(([brand, operational, serviceHealth]) => {
        if (!active) return
        setBranding(brand)
        setSettings(operational)
        setHealth(serviceHealth)
      })
      .catch((requestError) => {
        if (active) setError(requestError.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [])

  function updateSetting(name, value) {
    setSettings((current) => ({ ...current, [name]: value }))
  }

  async function saveSettings(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    try {
      await Promise.all([
        api.setBranding({ agency_name: branding.agency_name.trim() }),
        api.setSettings({
          broker_transfer_number: settings.broker_transfer_number || null,
          sms_sender_number: settings.sms_sender_number || null,
          whatsapp_sender_number: settings.whatsapp_sender_number || null,
          time_zone: settings.time_zone || null,
          business_hours_start_hour: settings.business_hours_start_hour === '' ? null : Number(settings.business_hours_start_hour),
          business_hours_end_hour: settings.business_hours_end_hour === '' ? null : Number(settings.business_hours_end_hour),
          voice_name: settings.voice_name || null,
          greeting: settings.greeting || null,
        }),
      ])
      setMessage('Settings saved.')
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  if (loading) return <p className="text-[13px] text-text-secondary">Loading settings...</p>
  if (error && (!branding || !settings)) {
    return <div role="alert" className="text-[13px] text-hot">{error}</div>
  }

  return (
    <div className="space-y-5 max-w-[900px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Settings</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">Configure agency, voice, operating hours, calendar, webhooks, and team access.</p>
      </div>

      {error && <div role="alert" className="rounded-lg bg-red-50 border border-red-100 p-3 text-[12px] text-hot">{error}</div>}
      {message && <div role="status" className="rounded-lg bg-green-50 p-3 text-[12px] text-green-700">{message}</div>}

      <form onSubmit={saveSettings} className="space-y-5">
        <Section icon={Building2} title="Agency" description="Branding used by your agent and dashboard.">
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Agency name" value={branding?.agency_name || ''} onChange={(value) => setBranding({ ...branding, agency_name: value })} required disabled={!canManage} />
            <label>
              <span className={labelClass}>Agency slug</span>
              <input className={`${fieldClass} bg-border-light text-text-muted`} value={tenantId} disabled />
            </label>
          </div>
        </Section>

        <Section icon={Phone} title="Phone numbers" description="Your inbound number is provisioned and routed by the platform operator.">
          <p className="text-[12px] text-text-secondary">
            To add or change an inbound number, contact the platform operator. Carrier and LiveKit routing must be configured together; this dashboard does not expose platform-level routing credentials.
          </p>
        </Section>

        <Section icon={Volume2} title="Voice & greeting" description="Settings applied to new calls for this agency.">
          <div className="grid sm:grid-cols-2 gap-4">
            <label>
              <span className={labelClass}>Voice</span>
              <select disabled={!canManage} className={fieldClass} value={settings?.voice_name || ''} onChange={(event) => updateSetting('voice_name', event.target.value)}>
                <option value="">Use platform default</option>
                {['Kore', 'Puck', 'Sulafat', 'Leda', 'Charon', 'Achird'].map((voice) => <option key={voice} value={voice}>{voice}</option>)}
              </select>
            </label>
            <Field label="Greeting" value={settings?.greeting || ''} onChange={(value) => updateSetting('greeting', value)} maxLength={500} disabled={!canManage} />
          </div>
        </Section>

        <Section icon={Globe} title="Business hours & time zone" description="Used for local scheduling and call handling.">
          <div className="grid sm:grid-cols-3 gap-4">
            <Field label="IANA time zone" value={settings?.time_zone || ''} onChange={(value) => updateSetting('time_zone', value)} placeholder="America/Chicago" disabled={!canManage} />
            <Field label="Business hours start (0–23)" type="number" min="0" max="23" value={settings?.business_hours_start_hour ?? ''} onChange={(value) => updateSetting('business_hours_start_hour', value)} disabled={!canManage} />
            <Field label="Business hours end (1–24)" type="number" min="1" max="24" value={settings?.business_hours_end_hour ?? ''} onChange={(value) => updateSetting('business_hours_end_hour', value)} disabled={!canManage} />
          </div>
        </Section>

        <Section icon={Phone} title="Transfer & messaging numbers" description="E.164 numbers used for human handoff and outbound notifications.">
          <div className="grid sm:grid-cols-3 gap-4">
            <Field label="Broker transfer number" value={settings?.broker_transfer_number || ''} onChange={(value) => updateSetting('broker_transfer_number', value)} placeholder="+15125550124" disabled={!canManage} />
            <Field label="SMS sender number" value={settings?.sms_sender_number || ''} onChange={(value) => updateSetting('sms_sender_number', value)} placeholder="+15125550125" disabled={!canManage} />
            <Field label="WhatsApp sender number" value={settings?.whatsapp_sender_number || ''} onChange={(value) => updateSetting('whatsapp_sender_number', value)} placeholder="+15125550126" disabled={!canManage} />
          </div>
        </Section>

        <div className="flex items-center justify-between">
          <span className="text-[12px] text-text-muted">{canManage ? 'Changes apply to new calls and messages.' : 'Only an agency owner can change these settings.'}</span>
          {canManage && <button type="submit" className="px-5 py-2 rounded-lg bg-accent text-white text-[13px] font-medium hover:bg-accent-hover">Save Settings</button>}
        </div>
      </form>

      <Section icon={CalendarDays} title="Google Calendar" description="Connect the agency calendar used for visit scheduling.">
        <CalendarConnection canManage={user?.role === 'owner'} />
      </Section>

      {canManage && (
        <>
          <Section icon={FileText} title="Knowledge base" description="Upload agency FAQs, policies, and property brochures for the AI agent.">
            <KnowledgeUpload />
          </Section>
          <Section icon={Webhook} title="Webhooks" description="Send signed event notifications to your HTTPS endpoint.">
            <WebhookManager />
          </Section>
          <Section icon={Users} title="Team members" description="Invite agents to access this agency dashboard.">
            <TeamManager />
          </Section>
        </>
      )}

      <Section icon={Shield} title="Service status" description="Live reachability checks from the Admin API.">
        <div className="space-y-2">
          {['admin-api', 'postgres', 'redis'].map((name) => {
            const state = name === 'admin-api' ? (health ? 'connected' : 'offline') : (health?.dependencies?.[name] || 'unknown')
            return (
              <div key={name} className="flex justify-between border-b border-border-light py-2 last:border-0">
                <span className="text-[13px] capitalize">{name === 'admin-api' ? 'Admin API' : name === 'postgres' ? 'PostgreSQL' : 'Redis'}</span>
                <span className={`text-[12px] font-medium ${state === 'connected' ? 'text-green-600' : 'text-hot'}`}>
                  {state === 'connected' ? 'Connected' : state === 'offline' ? 'Offline' : 'Unknown'}
                </span>
              </div>
            )
          })}
        </div>
      </Section>
    </div>
  )
}

function KnowledgeUpload() {
  const [file, setFile] = useState(null)
  const [sourceType, setSourceType] = useState('faq')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  async function upload(event) {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setMessage('')
    try {
      const result = await api.uploadKnowledgeDocument(file, sourceType)
      setMessage(`Uploaded ${result.filename}; ${result.chunks_created} knowledge chunks created.`)
      setFile(null)
      event.currentTarget.reset()
    } catch (requestError) {
      setMessage(`Upload failed: ${requestError.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={upload} className="flex flex-col sm:flex-row gap-3 sm:items-end">
      <label className="flex-1">
        <span className={labelClass}>PDF, TXT, or Markdown (max 10 MiB)</span>
        <input type="file" accept=".pdf,.txt,.md,text/plain,text/markdown,application/pdf" onChange={(event) => setFile(event.target.files?.[0] || null)} required className="w-full text-[12px]" />
      </label>
      <label>
        <span className={labelClass}>Document type</span>
        <select value={sourceType} onChange={(event) => setSourceType(event.target.value)} className={fieldClass}>
          {['faq', 'policy', 'brochure', 'other'].map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <button disabled={busy || !file} className="px-4 py-2 rounded-lg bg-accent text-white text-[12px] font-medium disabled:opacity-50">
        {busy ? 'Uploading...' : 'Upload document'}
      </button>
      {message && <p role="status" className={`text-[12px] ${message.startsWith('Upload failed') ? 'text-hot' : 'text-text-secondary'}`}>{message}</p>}
    </form>
  )
}

function CalendarConnection({ canManage }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (canManage) api.getCalendarStatus().then(setStatus).catch((requestError) => setError(requestError.message))
  }, [canManage])

  if (!canManage) return <p className="text-[12px] text-text-muted">Only an agency owner can manage calendar connections.</p>
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-3">
      <span className="text-[12px] text-text-secondary flex-1">
        {status?.connected ? `Connected: ${status.provider}` : 'Not connected'}
      </span>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          setError('')
          try {
            const { authorization_url: url } = await api.connectCalendar()
            window.location.assign(url)
          } catch (requestError) {
            setError(requestError.message)
            setBusy(false)
          }
        }}
        className="px-4 py-2 rounded-lg bg-accent text-white text-[12px] font-medium disabled:opacity-50"
      >
        {busy ? 'Opening Google...' : status?.connected ? 'Reconnect Google Calendar' : 'Connect Google Calendar'}
      </button>
      {error && <p role="alert" className="text-[12px] text-hot">{error}</p>}
    </div>
  )
}

function TeamManager() {
  const { user } = getAuth()
  const [team, setTeam] = useState([])
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function refresh() {
    try {
      const result = await api.listTeam()
      setTeam(result.items)
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  useEffect(() => {
    api.listTeam()
      .then((result) => setTeam(result.items))
      .catch((requestError) => setError(requestError.message))
  }, [])

  async function invite(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    try {
      await api.inviteTeamMember({ email, display_name: displayName })
      setMessage('Invitation sent.')
      setEmail('')
      setDisplayName('')
      await refresh()
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  async function deactivate(member) {
    if (!window.confirm(`Deactivate ${member.display_name}'s account?`)) return
    try {
      await api.deactivateTeamMember(member.id)
      setMessage(`${member.display_name} deactivated.`)
      await refresh()
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={invite} className="grid sm:grid-cols-[1fr_1fr_auto] gap-3 items-end">
        <Field label="Agent name" value={displayName} onChange={setDisplayName} required />
        <Field label="Agent email" type="email" value={email} onChange={setEmail} required />
        <button className="px-4 py-2 rounded-lg bg-accent text-white text-[12px] font-medium">Invite</button>
      </form>
      {message && <p role="status" className="text-[12px] text-green-700">{message}</p>}
      {error && <p role="alert" className="text-[12px] text-hot">{error}</p>}
      <ul className="divide-y divide-border-light">
        {team.map((member) => (
          <li key={member.id} className="py-2 flex justify-between text-[12px]">
            <span>{member.display_name} <span className="text-text-muted">({member.email})</span></span>
            <span className="text-text-muted capitalize">
              {member.role}{member.is_active ? '' : ' · inactive'}
              {member.is_active && member.id !== user?.id && (
                <button type="button" className="ml-3 text-hot" onClick={() => deactivate(member)}>Deactivate</button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function WebhookManager() {
  const [items, setItems] = useState([])
  const [url, setUrl] = useState('')
  const [events, setEvents] = useState(['lead.created'])
  const [secret, setSecret] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function refresh() {
    try {
      const result = await api.listWebhooks()
      setItems(result.items)
      setError('')
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  useEffect(() => {
    api.listWebhooks()
      .then((result) => setItems(result.items))
      .catch((requestError) => setError(requestError.message))
  }, [])

  async function create(event) {
    event.preventDefault()
    setError('')
    setMessage('')
    try {
      const result = await api.createWebhook({ target_url: url, events })
      setSecret(result.signing_secret)
      setMessage('Webhook created. Copy the signing secret now; it will not be shown again.')
      setUrl('')
      await refresh()
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  async function disable(id) {
    setError('')
    try {
      await api.deleteWebhook(id)
      await refresh()
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={create} className="space-y-3">
        <Field label="HTTPS endpoint" type="url" value={url} onChange={setUrl} placeholder="https://example.com/webhooks" required />
        <div className="flex flex-wrap gap-3">
          {['lead.created', 'lead.qualified', 'appointment.booked', 'call.completed'].map((eventName) => (
            <label key={eventName} className="flex gap-2 items-center text-[12px]">
              <input
                type="checkbox"
                checked={events.includes(eventName)}
                onChange={(event) => setEvents((current) => event.target.checked ? [...current, eventName] : current.filter((value) => value !== eventName))}
              />
              {eventName}
            </label>
          ))}
        </div>
        <button disabled={!events.length} className="px-4 py-2 rounded-lg bg-accent text-white text-[12px] font-medium disabled:opacity-50">Add webhook</button>
      </form>
      {message && <p role="status" className="text-[12px] text-green-700">{message}</p>}
      {secret && <p className="break-all rounded bg-border-light p-3 font-mono text-[11px]">Signing secret: {secret}</p>}
      {error && <p role="alert" className="text-[12px] text-hot">{error}</p>}
      <ul className="divide-y divide-border-light">
        {items.map((hook) => (
          <li key={hook.id} className="py-2 flex items-center gap-3 text-[12px]">
            <span className="flex-1 break-all">{hook.target_url}</span>
            <span className="text-text-muted">{hook.is_enabled ? 'Enabled' : 'Disabled'}</span>
            {hook.is_enabled && <button type="button" className="text-hot" onClick={() => disable(hook.id)}>Disable</button>}
          </li>
        ))}
      </ul>
    </div>
  )
}
