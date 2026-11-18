import { AlertCircle, Building2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, setAuth } from '../api'

function AccountFrame({ title, children }) {
  return (
    <div className="min-h-screen bg-bg flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="flex flex-col items-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-accent flex items-center justify-center mb-4">
            <Building2 size={22} className="text-white" />
          </div>
          <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Propview</h1>
          <p className="text-[13px] text-text-secondary mt-1">{title}</p>
        </div>
        {children}
      </div>
    </div>
  )
}

function AccountForm({ children, error, success, onSubmit }) {
  return (
    <form onSubmit={onSubmit} className="bg-bg-card rounded-xl border border-border p-5 space-y-4">
      {error && (
        <div role="alert" className="flex items-center gap-2 text-[12px] text-hot bg-red-50 border border-red-100 rounded-lg px-3 py-2">
          <AlertCircle size={14} />
          {error}
        </div>
      )}
      {success && <p role="status" className="text-[12px] text-accent">{success}</p>}
      {children}
    </form>
  )
}

function Field({ label, type = 'text', value, onChange, required = true, autoComplete, ...inputProps }) {
  return (
    <label className="block">
      <span className="text-[12px] text-text-secondary font-medium block mb-1.5">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        autoComplete={autoComplete}
        className="w-full px-3 py-2 rounded-lg border border-border text-[13px] outline-none focus:border-accent transition-colors"
        {...inputProps}
      />
    </label>
  )
}

function SubmitButton({ loading, children }) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="w-full py-2.5 rounded-lg bg-accent text-white text-[13px] font-medium hover:bg-accent-hover transition-colors disabled:opacity-50"
    >
      {loading ? 'Please wait...' : children}
    </button>
  )
}

export function Login({ onLogin }) {
  const navigate = useNavigate()
  const [tenantSlug, setTenantSlug] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      const result = await api.login(tenantSlug.trim(), email, password)
      setAuth(tenantSlug.trim(), result.access_token, result.user, result.expires_at)
      onLogin()
      navigate('/', { replace: true })
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AccountFrame title="Sign in to your agency dashboard">
      <AccountForm onSubmit={handleSubmit} error={error}>
        <Field label="Agency slug" value={tenantSlug} onChange={setTenantSlug} autoComplete="organization" />
        <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="username" />
        <Field label="Password" type="password" value={password} onChange={setPassword} autoComplete="current-password" />
        <SubmitButton loading={loading}>Sign In</SubmitButton>
        <div className="flex justify-between text-[12px]">
          <Link className="text-accent hover:underline" to="/forgot-password">Forgot password?</Link>
          <Link className="text-accent hover:underline" to="/signup">Create an agency account</Link>
        </div>
      </AccountForm>
    </AccountFrame>
  )
}

export function Signup() {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    tenant_slug: '',
    tenant_name: '',
    owner_name: '',
    email: '',
    password: '',
  })
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      const result = await api.signup(form)
      setSuccess(`Check ${form.email} for a verification link. Your agency slug is ${result.tenant_slug}.`)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AccountFrame title="Create your agency account">
      <AccountForm onSubmit={handleSubmit} error={error} success={success}>
        <Field label="Agency name" value={form.tenant_name} onChange={(value) => update('tenant_name', value)} autoComplete="organization" />
        <Field label="Agency slug" value={form.tenant_slug} onChange={(value) => update('tenant_slug', value.toLowerCase())} autoComplete="off" />
        <Field label="Your name" value={form.owner_name} onChange={(value) => update('owner_name', value)} autoComplete="name" />
        <Field label="Email" type="email" value={form.email} onChange={(value) => update('email', value)} autoComplete="email" />
        <Field label="Password (at least 12 characters)" type="password" value={form.password} onChange={(value) => update('password', value)} autoComplete="new-password" />
        <SubmitButton loading={loading}>Create Account</SubmitButton>
        <p className="text-[12px] text-text-muted text-center">
          Already registered? <Link className="text-accent hover:underline" to="/login">Sign in</Link>
        </p>
        {success && <button type="button" className="w-full text-[12px] text-accent hover:underline" onClick={() => navigate('/login')}>Return to sign in</button>}
      </AccountForm>
    </AccountFrame>
  )
}

export function VerifyEmail() {
  const [params] = useSearchParams()
  const [tenant, setTenant] = useState(params.get('tenant') || '')
  const token = params.get('token') || ''
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [email, setEmail] = useState('')

  async function verify(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.verifyEmail(tenant, token)
      setMessage('Email verified. You can now sign in.')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  async function resend(event) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.resendVerification(tenant, email)
      setMessage('If verification is pending, a new link has been sent.')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AccountFrame title="Verify your email address">
      <AccountForm onSubmit={token ? verify : resend} error={error} success={message}>
        {token ? (
          <SubmitButton loading={loading}>Verify Email</SubmitButton>
        ) : (
          <>
            <p className="text-[12px] text-text-secondary">Enter the agency slug and email used for signup to request another verification link.</p>
            <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" />
            <SubmitButton loading={loading}>Resend Verification</SubmitButton>
          </>
        )}
        {!token && <Field label="Agency slug" value={tenant} onChange={setTenant} />}
        <Link className="block text-center text-[12px] text-accent hover:underline" to="/login">Back to sign in</Link>
      </AccountForm>
    </AccountFrame>
  )
}

function TenantTokenPasswordPage({ invitation = false }) {
  const [params] = useSearchParams()
  const tenant = params.get('tenant') || ''
  const token = params.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    if (password !== confirmation) {
      setError('Passwords do not match.')
      return
    }
    setLoading(true)
    try {
      if (invitation) await api.acceptInvitation(tenant, token, password)
      else await api.resetPassword(tenant, token, password)
      setSuccess(invitation ? 'Invitation accepted. You can sign in now.' : 'Password updated. You can sign in now.')
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AccountFrame title={invitation ? 'Accept your team invitation' : 'Set a new password'}>
      <AccountForm onSubmit={handleSubmit} error={error} success={success}>
        <Field label="New password (at least 12 characters)" type="password" value={password} onChange={setPassword} autoComplete="new-password" />
        <Field label="Confirm password" type="password" value={confirmation} onChange={setConfirmation} autoComplete="new-password" />
        <SubmitButton loading={loading}>{invitation ? 'Accept Invitation' : 'Reset Password'}</SubmitButton>
        <Link className="block text-center text-[12px] text-accent hover:underline" to="/login">Back to sign in</Link>
      </AccountForm>
    </AccountFrame>
  )
}

export function ResetPassword() {
  return <TenantTokenPasswordPage />
}

export function AcceptInvitation() {
  return <TenantTokenPasswordPage invitation />
}

export function ForgotPassword() {
  const [tenantSlug, setTenantSlug] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      const result = await api.requestPasswordReset(tenantSlug.trim(), email)
      setSuccess(result.status)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <AccountFrame title="Reset your password">
      <AccountForm onSubmit={handleSubmit} error={error} success={success}>
        <Field label="Agency slug" value={tenantSlug} onChange={setTenantSlug} autoComplete="organization" />
        <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" />
        <SubmitButton loading={loading}>Send Reset Link</SubmitButton>
        <Link className="block text-center text-[12px] text-accent hover:underline" to="/login">Back to sign in</Link>
      </AccountForm>
    </AccountFrame>
  )
}
