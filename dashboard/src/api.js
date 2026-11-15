const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001'
const SESSION_KEY = 'propview_session_token'
const TENANT_KEY = 'propview_session_tenant'
const USER_KEY = 'propview_session_user'
const EXPIRES_KEY = 'propview_session_expires'

localStorage.removeItem('propview_api_key')
localStorage.removeItem('propview_tenant_id')

let authExpiredHandler = null

function readAuth() {
  try {
    return {
      tenantId: sessionStorage.getItem(TENANT_KEY) || '',
      sessionToken: sessionStorage.getItem(SESSION_KEY) || '',
      user: JSON.parse(sessionStorage.getItem(USER_KEY) || 'null'),
    }
  } catch {
    return { tenantId: '', sessionToken: '', user: null }
  }
}

export function getAuth() {
  return readAuth()
}

export function setAuth(tenantId, sessionToken, user, expiresAt) {
  sessionStorage.setItem(TENANT_KEY, tenantId)
  sessionStorage.setItem(SESSION_KEY, sessionToken)
  sessionStorage.setItem(USER_KEY, JSON.stringify(user))
  if (expiresAt) sessionStorage.setItem(EXPIRES_KEY, expiresAt)
}

export function clearAuth() {
  sessionStorage.removeItem(TENANT_KEY)
  sessionStorage.removeItem(SESSION_KEY)
  sessionStorage.removeItem(USER_KEY)
  sessionStorage.removeItem(EXPIRES_KEY)
}

export function isAuthenticated() {
  const { tenantId, sessionToken } = readAuth()
  const expiresAt = sessionStorage.getItem(EXPIRES_KEY)
  if (expiresAt && Date.parse(expiresAt) <= Date.now()) {
    clearAuth()
    return false
  }
  return Boolean(tenantId && sessionToken)
}

export function onAuthExpired(handler) {
  authExpiredHandler = handler
  return () => {
    if (authExpiredHandler === handler) authExpiredHandler = null
  }
}

async function request(path, options = {}) {
  const { sessionToken } = readAuth()
  const headers = new Headers(options.headers || {})
  if (sessionToken) headers.set('Authorization', `Bearer ${sessionToken}`)
  if (!(options.body instanceof FormData) && options.body != null) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (res.status === 401) {
    clearAuth()
    authExpiredHandler?.()
    throw new Error('Your session expired. Please sign in again.')
  }
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  if (res.status === 204) return null
  return res.json()
}

function tenantPath(path) {
  const { tenantId } = readAuth()
  if (!tenantId) throw new Error('No tenant is associated with this session.')
  return `/admin/tenants/${encodeURIComponent(tenantId)}${path}`
}

export const api = {
  health: () => request('/health'),
  login: (tenantSlug, email, password) =>
    request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ tenant_slug: tenantSlug, email, password }),
    }),
  signup: (data) =>
    request('/auth/signup', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  verifyEmail: (tenantId, token) =>
    request(`/auth/${encodeURIComponent(tenantId)}/verify-email`, {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),
  resendVerification: (tenantId, email) =>
    request(`/auth/${encodeURIComponent(tenantId)}/verification/resend`, {
      method: 'POST',
      body: JSON.stringify({ tenant_slug: tenantId, email }),
    }),
  requestPasswordReset: (tenantId, email) =>
    request('/auth/password-reset/request', {
      method: 'POST',
      body: JSON.stringify({ tenant_slug: tenantId, email }),
    }),
  resetPassword: (tenantId, token, password) =>
    request('/auth/password-reset/confirm', {
      method: 'POST',
      body: JSON.stringify({ tenant_slug: tenantId, token, password }),
    }),
  acceptInvitation: (tenantId, token, password) =>
    request(`/auth/${encodeURIComponent(tenantId)}/team/accept`, {
      method: 'POST',
      body: JSON.stringify({ token, password }),
    }),
  logout: () =>
    request(`/auth/${encodeURIComponent(readAuth().tenantId)}/logout`, { method: 'POST' }).finally(clearAuth),
  me: () => request(`/auth/${encodeURIComponent(readAuth().tenantId)}/me`),

  getStats: () => request(tenantPath('/stats')),
  getBranding: () => request(tenantPath('/branding')),
  setBranding: (data) =>
    request(tenantPath('/branding'), { method: 'PUT', body: JSON.stringify(data) }),
  getSettings: () => request(tenantPath('/settings')),
  setSettings: (data) =>
    request(tenantPath('/settings'), { method: 'PUT', body: JSON.stringify(data) }),
  getCalendarStatus: () => request(tenantPath('/calendar/google/status')),
  connectCalendar: () => request(tenantPath('/calendar/google/connect')),
  listTeam: () => request(tenantPath('/team')),
  inviteTeamMember: (data) =>
    request(tenantPath('/team/invitations'), { method: 'POST', body: JSON.stringify(data) }),
  deactivateTeamMember: (userId) =>
    request(tenantPath(`/team/${encodeURIComponent(userId)}`), { method: 'DELETE' }),
  listWebhooks: () => request(tenantPath('/webhooks')),
  createWebhook: (data) =>
    request(tenantPath('/webhooks'), { method: 'POST', body: JSON.stringify(data) }),
  deleteWebhook: (webhookId) =>
    request(tenantPath(`/webhooks/${encodeURIComponent(webhookId)}`), { method: 'DELETE' }),
  listWebhookDeliveries: (webhookId) =>
    request(tenantPath(`/webhooks/${encodeURIComponent(webhookId)}/deliveries`)),
  getUsage: () => request(tenantPath('/usage/monthly')),
  getBilling: () => request(tenantPath('/billing')),
  createSubscription: (planSlug) =>
    request(tenantPath('/billing/subscription'), {
      method: 'POST',
      body: JSON.stringify({ plan_slug: planSlug }),
    }),

  listProperties: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(tenantPath(`/properties${qs ? `?${qs}` : ''}`))
  },
  listLeads: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(tenantPath(`/leads${qs ? `?${qs}` : ''}`))
  },
  listAppointments: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(tenantPath(`/appointments${qs ? `?${qs}` : ''}`))
  },
  listCalls: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(tenantPath(`/calls${qs ? `?${qs}` : ''}`))
  },
  getCallDetail: (callId) =>
    request(tenantPath(`/calls/${encodeURIComponent(callId)}`)),
  updateLead: (leadId, data) =>
    request(tenantPath(`/leads/${encodeURIComponent(leadId)}`), {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  updateAppointment: (appointmentId, data) =>
    request(tenantPath(`/appointments/${encodeURIComponent(appointmentId)}`), {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  cancelAppointment: (appointmentId) =>
    request(tenantPath(`/appointments/${encodeURIComponent(appointmentId)}`), {
      method: 'PATCH',
      body: JSON.stringify({ status: 'cancelled' }),
    }),
  updateProperty: (propertyId, data) =>
    request(tenantPath(`/properties/${encodeURIComponent(propertyId)}`), {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteProperty: (propertyId) =>
    request(tenantPath(`/properties/${encodeURIComponent(propertyId)}`), {
      method: 'DELETE',
    }),
  uploadListings: (file) => {
    const body = new FormData()
    body.append('file', file)
    return request(tenantPath('/listings/upload-csv'), { method: 'POST', body })
  },
  uploadKnowledgeDocument: (file, sourceType = 'other') => {
    const body = new FormData()
    body.append('file', file)
    body.append('source_type', sourceType)
    return request(tenantPath('/knowledge-base/documents'), { method: 'POST', body })
  },
}
