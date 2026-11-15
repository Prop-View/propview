import { expect, test } from '@playwright/test'

test('agency account login opens the dashboard without persisting credentials to localStorage', async ({ page }) => {
  const corsHeaders = {
    'access-control-allow-origin': 'http://127.0.0.1:5174',
    'access-control-allow-headers': 'Authorization, Content-Type',
    'access-control-allow-methods': 'GET, POST, OPTIONS',
  }
  await page.route('http://localhost:8001/**', async (route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: corsHeaders })
      return
    }
    await route.fallback()
  })
  await page.route('http://localhost:8001/auth/login', async (route) => {
    const body = route.request().postDataJSON()
    expect(body).toEqual({
      tenant_slug: 'smoke-agency',
      email: 'owner@example.test',
      password: 'correct horse battery',
    })
    await route.fulfill({
      contentType: 'application/json',
      headers: corsHeaders,
      body: JSON.stringify({
        access_token: 'smoke-session-token',
        token_type: 'bearer',
        expires_at: '2030-01-01T00:00:00Z',
        user: { id: 1, email: 'owner@example.test', display_name: 'Owner', role: 'owner' },
      }),
    })
  })
  await page.route('http://localhost:8001/admin/tenants/smoke-agency/branding', (route) =>
    route.fulfill({ contentType: 'application/json', headers: corsHeaders, body: JSON.stringify({ agency_name: 'Smoke Realty' }) }),
  )
  await page.route('http://localhost:8001/health', (route) =>
    route.fulfill({
      contentType: 'application/json',
      headers: corsHeaders,
      body: JSON.stringify({ status: 'ok', dependencies: { postgres: 'connected', redis: 'connected' } }),
    }),
  )
  await page.route('http://localhost:8001/admin/tenants/smoke-agency/stats', (route) =>
    route.fulfill({
      contentType: 'application/json',
      headers: corsHeaders,
      body: JSON.stringify({
        calls_today: 0,
        total_calls: 0,
        avg_duration_seconds: 0,
        conversion_rate: 0,
        hot_leads: 0,
        active_leads: 0,
        daily_calls: [],
        daily_bookings: [],
        lead_priority_counts: {},
        tool_usage: [],
      }),
    }),
  )
  await page.route('http://localhost:8001/admin/tenants/smoke-agency/calls?limit=5', (route) =>
    route.fulfill({ contentType: 'application/json', headers: corsHeaders, body: JSON.stringify({ items: [], total: 0 }) }),
  )

  await page.goto('/login')
  await page.getByLabel('Agency slug').fill('smoke-agency')
  await page.getByLabel('Email').fill('owner@example.test')
  await page.getByLabel('Password').fill('correct horse battery')
  await page.getByRole('button', { name: 'Sign In' }).click()

  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('propview_session_token')))
    .toBe('smoke-session-token')
  const legacyStorage = await page.evaluate(() => ({
    apiKey: localStorage.getItem('propview_api_key'),
    tenantId: localStorage.getItem('propview_tenant_id'),
  }))
  expect(legacyStorage).toEqual({ apiKey: null, tenantId: null })
})
