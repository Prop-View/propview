import { CreditCard, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import useApi from '../hooks/useApi'

const USAGE_TYPES = [
  { key: 'call', limit: 'calls_limit', label: 'Calls' },
  { key: 'sms', limit: 'sms_limit', label: 'SMS' },
  { key: 'whatsapp', limit: 'whatsapp_limit', label: 'WhatsApp' },
]

function formatPrice(amountMinor, currency) {
  if (amountMinor == null || !currency) return 'Pricing not configured'
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
  }).format(amountMinor / 100)
}

export default function Usage() {
  const { data, loading, error, refetch } = useApi(() => api.getBilling(), [])
  const [busyPlan, setBusyPlan] = useState('')
  const [actionError, setActionError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const items = data?.usage?.items || []
  const usageByType = Object.fromEntries(items.map((item) => [item.event_type, Number(item.units)]))
  const plans = data?.plans || []
  const subscription = data?.subscription
  const currentPlan = plans.find((plan) => plan.slug === subscription?.plan_slug)
  const openSubscription = subscription && !['cancelled', 'completed', 'expired', 'failed'].includes(subscription.status)

  async function subscribe(plan) {
    setBusyPlan(plan.slug)
    setActionError('')
    setActionMessage('')
    try {
      const result = await api.createSubscription(plan.slug)
      setActionMessage('Your test-mode subscription was created. Continue to Razorpay to complete checkout.')
      if (result.checkout_url) window.location.assign(result.checkout_url)
      else refetch()
    } catch (requestError) {
      setActionError(requestError.message)
    } finally {
      setBusyPlan('')
    }
  }

  if (loading) return <Loading />
  if (error) return <ErrorState message={error} onRetry={refetch} />

  return (
    <div className="space-y-5 max-w-[1000px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Usage & Billing</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          Metered activity and subscription status for your agency
        </p>
      </div>

      {actionError && <p role="alert" className="rounded-lg bg-red-50 p-3 text-[12px] text-hot">{actionError}</p>}
      {actionMessage && <p role="status" className="rounded-lg bg-green-50 p-3 text-[12px] text-green-700">{actionMessage}</p>}

      <section className="bg-bg-card rounded-xl border border-border p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[14px] font-semibold">Current subscription</h2>
            <p className="text-[12px] text-text-secondary mt-1">
              {subscription
                ? `${subscription.plan_name} · ${subscription.status}`
                : 'No subscription is active for this agency.'}
            </p>
            {subscription?.current_period_end && (
              <p className="text-[11px] text-text-muted mt-1">
                Current period ends {new Date(subscription.current_period_end).toLocaleDateString()}
              </p>
            )}
          </div>
          {subscription?.checkout_url && ['created', 'authenticated', 'pending'].includes(subscription.status) && (
            <a
              href={subscription.checkout_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent text-white text-[12px] font-medium"
            >
              Continue checkout <ExternalLink size={13} />
            </a>
          )}
        </div>
        <p className="text-[11px] text-text-muted mt-3">
          Razorpay is restricted to test credentials. Usage limits are advisory only and never stop or interrupt a live call.
        </p>
      </section>

      {(data?.warnings || []).map((warning) => (
        <div
          key={warning.event_type}
          role="status"
          className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800"
        >
          {warning.level === 'limit_reached' ? 'Usage limit reached' : 'Approaching usage limit'}: {warning.used} of {warning.limit} {warning.event_type} units this month. Service remains available.
        </div>
      ))}

      <section className="bg-bg-card rounded-xl border border-border p-5">
        <h2 className="text-[14px] font-semibold">This month’s usage</h2>
        <p className="text-[11px] text-text-muted mt-1">{data?.usage?.month || 'Current month'}</p>
        <div className="grid sm:grid-cols-3 gap-3 mt-4">
          {USAGE_TYPES.map(({ key, limit, label }) => {
            const used = usageByType[key] || 0
            const max = currentPlan?.[limit]
            const percentage = max ? Math.min(100, Math.round((used / max) * 100)) : 0
            return (
              <div key={key} className="rounded-lg border border-border-light p-4">
                <div className="text-[12px] text-text-muted">{label}</div>
                <div className="text-[20px] font-semibold mt-1">{used.toLocaleString()}</div>
                <div className="text-[11px] text-text-muted">
                  {max == null ? 'No configured limit' : `of ${max.toLocaleString()} units`}
                </div>
                {max != null && (
                  <div className="h-1.5 rounded-full bg-border-light mt-3 overflow-hidden" aria-label={`${label} usage ${percentage}%`}>
                    <div className="h-full bg-accent" style={{ width: `${percentage}%` }} />
                  </div>
                )}
              </div>
            )
          })}
        </div>

        <div className="overflow-x-auto mt-5 border border-border rounded-lg">
          <table className="w-full text-left text-[12px]">
            <thead className="border-b border-border-light text-text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">Month</th>
                <th className="px-4 py-3 font-medium">Usage type</th>
                <th className="px-4 py-3 font-medium">Events</th>
                <th className="px-4 py-3 font-medium">Units</th>
              </tr>
            </thead>
            <tbody>
              {items.length ? items.map((item) => (
                <tr key={`${item.month}-${item.event_type}`} className="border-b border-border-light last:border-0">
                  <td className="px-4 py-3">{new Date(item.month).toLocaleDateString([], { year: 'numeric', month: 'long' })}</td>
                  <td className="px-4 py-3 capitalize">{item.event_type.replaceAll('_', ' ')}</td>
                  <td className="px-4 py-3">{Number(item.event_count).toLocaleString()}</td>
                  <td className="px-4 py-3">{Number(item.units).toLocaleString()}</td>
                </tr>
              )) : (
                <tr><td className="px-4 py-4 text-text-muted" colSpan="4">No usage has been recorded this month.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-[14px] font-semibold">Available plans</h2>
          <p className="text-[12px] text-text-secondary mt-1">
            Plans and prices are managed by the platform operator. Checkout is test mode only.
          </p>
        </div>
        {plans.length === 0 ? (
          <EmptyState
            icon={CreditCard}
            title="No plans are configured"
            description="The platform operator must configure the plan catalog before checkout is available."
          />
        ) : (
          <div className="grid md:grid-cols-2 gap-3">
            {plans.map((plan) => {
              const eligible = data?.provider_configured && plan.provider_plan_configured && plan.price_minor != null
              return (
                <article key={plan.slug} className="bg-bg-card rounded-xl border border-border p-5">
                  <h3 className="text-[14px] font-semibold">{plan.display_name}</h3>
                  {plan.description && <p className="text-[12px] text-text-secondary mt-1">{plan.description}</p>}
                  <p className="text-[20px] font-semibold mt-3">{formatPrice(plan.price_minor, plan.currency)}</p>
                  <ul className="mt-3 space-y-1 text-[11px] text-text-muted">
                    {USAGE_TYPES.map(({ key, limit, label }) => (
                      <li key={key}>{plan[limit] == null ? 'Unlimited' : Number(plan[limit]).toLocaleString()} {label.toLowerCase()} / month</li>
                    ))}
                  </ul>
                  {!openSubscription && (
                    <button
                      type="button"
                      disabled={!eligible || busyPlan !== ''}
                      onClick={() => subscribe(plan)}
                      className="mt-4 px-4 py-2 rounded-lg bg-accent text-white text-[12px] font-medium disabled:opacity-50"
                    >
                      {busyPlan === plan.slug ? 'Preparing checkout...' : eligible ? 'Choose plan' : 'Not available'}
                    </button>
                  )}
                  {!eligible && <p className="mt-2 text-[11px] text-text-muted">Test-mode price and provider plan are not configured.</p>}
                </article>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
