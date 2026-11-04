const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8100'

let _tenantId = localStorage.getItem('propview_tenant_id') || ''
let _apiKey = localStorage.getItem('propview_api_key') || ''

export function getAuth() {
  return { tenantId: _tenantId, apiKey: _apiKey }
}

export function setAuth(tenantId, apiKey) {
  _tenantId = tenantId
  _apiKey = apiKey
  localStorage.setItem('propview_tenant_id', tenantId)
  localStorage.setItem('propview_api_key', apiKey)
}

export function clearAuth() {
  _tenantId = ''
  _apiKey = ''
  localStorage.removeItem('propview_tenant_id')
  localStorage.removeItem('propview_api_key')
}

export function isAuthenticated() {
  return Boolean(_tenantId && _apiKey)
}

async function request(path, options = {}) {
  const url = `${API_BASE}/admin/tenants/${encodeURIComponent(_tenantId)}${path}`
  const res = await fetch(url, {
    ...options,
    headers: {
      'Authorization': `Bearer ${_apiKey}`,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })
  if (res.status === 401) {
    clearAuth()
    window.location.reload()
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  return res.json()
}

export const api = {
  health: () => fetch(`${API_BASE}/health`).then((r) => r.json()),

  getStats: () => request('/stats'),
  getBranding: () => request('/branding'),

  listProperties: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/properties${qs ? '?' + qs : ''}`)
  },

  listLeads: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/leads${qs ? '?' + qs : ''}`)
  },

  listAppointments: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/appointments${qs ? '?' + qs : ''}`)
  },

  listCalls: (params = {}) => {
    const qs = new URLSearchParams(params).toString()
    return request(`/calls${qs ? '?' + qs : ''}`)
  },

  getCallDetail: (callId) => request(`/calls/${encodeURIComponent(callId)}`),

  setBranding: (data) =>
    request('/branding', { method: 'PUT', body: JSON.stringify(data) }),

  uploadListings: (listings) =>
    request('/listings', { method: 'POST', body: JSON.stringify({ listings }) }),
}
