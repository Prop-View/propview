import { AlertCircle, Building2 } from 'lucide-react'
import { useState } from 'react'
import { api, setAuth } from '../api'

export default function Login({ onLogin }) {
  const [tenantId, setTenantId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!tenantId.trim() || !apiKey.trim()) return

    setLoading(true)
    setError('')

    setAuth(tenantId.trim(), apiKey.trim())
    try {
      await api.getBranding()
      onLogin()
    } catch {
      setError('Invalid tenant ID or API key')
      setAuth('', '')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-accent flex items-center justify-center mb-4">
            <Building2 size={22} className="text-white" />
          </div>
          <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Propview</h1>
          <p className="text-[13px] text-text-secondary mt-1">
            Sign in to your agency dashboard
          </p>
        </div>

        <form onSubmit={handleSubmit} className="bg-bg-card rounded-xl border border-border p-5 space-y-4">
          {error && (
            <div className="flex items-center gap-2 text-[12px] text-hot bg-red-50 border border-red-100 rounded-lg px-3 py-2">
              <AlertCircle size={14} />
              {error}
            </div>
          )}

          <div>
            <label className="text-[12px] text-text-secondary font-medium block mb-1.5">
              Tenant ID
            </label>
            <input
              type="text"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              placeholder="e.g. default"
              className="w-full px-3 py-2 rounded-lg border border-border text-[13px] outline-none focus:border-accent transition-colors"
              autoFocus
            />
          </div>

          <div>
            <label className="text-[12px] text-text-secondary font-medium block mb-1.5">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Your tenant admin API key"
              className="w-full px-3 py-2 rounded-lg border border-border text-[13px] font-mono outline-none focus:border-accent transition-colors"
            />
          </div>

          <button
            type="submit"
            disabled={loading || !tenantId.trim() || !apiKey.trim()}
            className="w-full py-2.5 rounded-lg bg-accent text-white text-[13px] font-medium hover:bg-accent-hover transition-colors disabled:opacity-50"
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>

          <p className="text-[11px] text-text-muted text-center">
            API key was provided when your tenant was provisioned.
            <br />
            Contact your platform operator if you need a new one.
          </p>
        </form>
      </div>
    </div>
  )
}
