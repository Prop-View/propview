import { Building2, Globe, Key, Mic, Shield, Volume2 } from 'lucide-react'
import { useState } from 'react'
import { api, getAuth } from '../api'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import useApi from '../hooks/useApi'

function Section({ icon: Icon, title, desc, children }) {
  return (
    <div className="bg-bg-card rounded-xl border border-border p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-9 h-9 rounded-lg bg-border-light flex items-center justify-center shrink-0">
          <Icon size={17} className="text-text-secondary" />
        </div>
        <div>
          <h2 className="text-[14px] font-semibold">{title}</h2>
          <p className="text-[12px] text-text-muted mt-0.5">{desc}</p>
        </div>
      </div>
      {children}
    </div>
  )
}

export default function Settings() {
  const { tenantId } = getAuth()
  const { data: branding, loading, error, refetch } = useApi(() => api.getBranding(), [])
  const [agencyName, setAgencyName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

  const currentName = agencyName || branding?.agency_name || ''

  async function handleSave() {
    if (!currentName.trim()) return
    setSaving(true)
    setSaveMsg('')
    try {
      await api.setBranding({ agency_name: currentName.trim() })
      setSaveMsg('Saved')
      refetch()
    } catch (e) {
      setSaveMsg(`Error: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Loading />
  if (error) return <ErrorState message={error} onRetry={refetch} />

  return (
    <div className="space-y-5 max-w-[800px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Settings</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          Configure your AI agent and tenant settings
        </p>
      </div>

      <Section icon={Building2} title="Agency Branding" desc="How your agency appears to callers">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="text-[12px] text-text-secondary font-medium block mb-1.5">
              Agency Name
            </label>
            <input
              type="text"
              value={currentName}
              onChange={(e) => setAgencyName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border text-[13px] outline-none focus:border-accent transition-colors"
            />
          </div>
          <div>
            <label className="text-[12px] text-text-secondary font-medium block mb-1.5">
              Tenant ID
            </label>
            <input
              type="text"
              value={tenantId}
              disabled
              className="w-full px-3 py-2 rounded-lg border border-border text-[13px] font-mono outline-none bg-border-light text-text-muted"
            />
          </div>
        </div>
      </Section>

      <Section icon={Volume2} title="Voice Configuration" desc="Gemini Live voice settings for the AI agent">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="text-[12px] text-text-secondary font-medium block mb-1.5">
              Voice Name
            </label>
            <select className="w-full px-3 py-2 rounded-lg border border-border text-[13px] outline-none focus:border-accent bg-bg-card">
              {['Kore', 'Puck', 'Sulafat', 'Leda', 'Charon', 'Achird'].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[12px] text-text-secondary font-medium block mb-1.5">
              Model
            </label>
            <input
              type="text"
              value="gemini-3.1-flash-live-preview"
              disabled
              className="w-full px-3 py-2 rounded-lg border border-border text-[13px] font-mono outline-none bg-border-light text-text-muted"
            />
          </div>
        </div>
        <div className="mt-3 flex items-center gap-2 text-[12px] text-text-muted">
          <Mic size={13} />
          Voice selection is configured via GEMINI_VOICE_NAME in the orchestrator .env
        </div>
      </Section>

      <Section icon={Key} title="Authentication" desc="API keys and service tokens">
        <div className="space-y-4">
          <div>
            <label className="text-[12px] text-text-secondary font-medium block mb-1.5">
              Admin API Key
            </label>
            <input
              type="password"
              value="pv_live_••••••••••••••••"
              disabled
              className="w-full px-3 py-2 rounded-lg border border-border text-[13px] font-mono outline-none bg-border-light text-text-muted"
            />
          </div>
          <div className="text-[12px] text-text-muted flex items-center gap-1.5">
            <Shield size={12} />
            Keys are hashed at rest (SHA-256) and shown only once at provisioning time
          </div>
        </div>
      </Section>

      <Section icon={Globe} title="Service Status" desc="Backend service health">
        <ServiceStatus />
      </Section>

      <div className="flex items-center justify-between pb-4">
        {saveMsg && (
          <span className={`text-[12px] ${saveMsg.startsWith('Error') ? 'text-hot' : 'text-accent'}`}>
            {saveMsg}
          </span>
        )}
        <div className="flex-1" />
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 rounded-lg bg-accent text-white text-[13px] font-medium hover:bg-accent-hover transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </div>
  )
}

function ServiceStatus() {
  const { data: health, loading } = useApi(() => api.health(), [])

  const services = [
    { name: 'Admin API', status: loading ? 'checking' : health?.status === 'ok' ? 'connected' : 'offline' },
    { name: 'Tool Router', status: 'check env', detail: 'Separate service (port 8000)' },
    { name: 'LiveKit Server', status: 'check env', detail: 'Required for calls' },
    { name: 'PostgreSQL', status: loading ? 'checking' : health?.status === 'ok' ? 'connected' : 'offline', detail: 'RLS-enforced via propview_app role' },
    { name: 'Redis', status: 'check env', detail: 'Session store + rate limiting' },
  ]

  return (
    <div className="space-y-3">
      {services.map((svc) => (
        <div
          key={svc.name}
          className="flex items-center justify-between py-2.5 border-b border-border-light last:border-0"
        >
          <div>
            <div className="text-[13px] font-medium">{svc.name}</div>
            {svc.detail && <div className="text-[11px] text-text-muted">{svc.detail}</div>}
          </div>
          <span
            className={`text-[11px] font-semibold px-2 py-0.5 rounded-md ${
              svc.status === 'connected'
                ? 'bg-green-50 text-green-600'
                : svc.status === 'offline'
                  ? 'bg-red-50 text-red-600'
                  : 'bg-amber-50 text-amber-600'
            }`}
          >
            {svc.status === 'connected' ? 'Connected' : svc.status === 'offline' ? 'Offline' : 'Check Env'}
          </span>
        </div>
      ))}
    </div>
  )
}
