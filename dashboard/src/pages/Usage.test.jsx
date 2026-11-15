import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import Usage from './Usage'

vi.mock('../api', () => ({
  api: {
    getBilling: vi.fn(),
    createSubscription: vi.fn(),
  },
}))

describe('Usage and billing page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getBilling.mockResolvedValue({
      provider: 'razorpay',
      provider_configured: true,
      plans: [{
        slug: 'agency',
        display_name: 'Agency',
        price_minor: 129900,
        currency: 'INR',
        calls_limit: 100,
        sms_limit: null,
        whatsapp_limit: 50,
        provider_plan_configured: true,
      }],
      subscription: {
        plan_slug: 'agency',
        plan_name: 'Agency',
        status: 'active',
      },
      usage: {
        month: '2026-11',
        items: [{ month: '2026-11-01T00:00:00Z', event_type: 'call', event_count: 81, units: 81 }],
      },
      warnings: [{ event_type: 'call', used: 81, limit: 100, level: 'approaching_limit' }],
      limits_are_advisory: true,
    })
  })

  afterEach(() => cleanup())

  it('renders subscription, metered usage and advisory warnings', async () => {
    render(<Usage />)

    expect(await screen.findByText('Agency · active')).toBeTruthy()
    expect(screen.getByText(/81 of 100 call units this month/)).toBeTruthy()
    expect(screen.getAllByText('81').length).toBeGreaterThan(0)
    expect(screen.getByText('No configured limit')).toBeTruthy()
    await waitFor(() => expect(api.getBilling).toHaveBeenCalledOnce())
  })

  it('shows when the operator has not configured a plan catalog', async () => {
    api.getBilling.mockResolvedValue({
      provider: 'razorpay',
      provider_configured: false,
      plans: [],
      subscription: null,
      usage: { month: '2026-11', items: [] },
      warnings: [],
      limits_are_advisory: true,
    })

    render(<Usage />)

    expect(await screen.findByText('No plans are configured')).toBeTruthy()
    expect(screen.getByText(/never stop or interrupt a live call/)).toBeTruthy()
  })
})
