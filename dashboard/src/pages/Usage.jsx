import { CreditCard } from 'lucide-react'
import { api } from '../api'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import useApi from '../hooks/useApi'

export default function Usage() {
  const { data, loading, error, refetch } = useApi(() => api.getUsage(), [])
  const items = data?.items || []
  const totals = items.reduce((result, item) => {
    result[item.event_type] = (result[item.event_type] || 0) + Number(item.event_count || 0)
    return result
  }, {})

  return (
    <div className="space-y-5 max-w-[1000px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Usage & Billing</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          Metered calls and messaging usage recorded for your agency
        </p>
      </div>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={CreditCard}
          title="No usage recorded yet"
          description="Usage appears here after calls and messages are metered."
        />
      ) : (
        <>
          <div className="grid sm:grid-cols-3 gap-3">
            {Object.entries(totals).map(([type, count]) => (
              <div key={type} className="bg-bg-card rounded-xl border border-border p-4">
                <div className="text-[12px] text-text-muted capitalize">{type.replaceAll('_', ' ')}</div>
                <div className="text-[22px] font-semibold mt-1">{count.toLocaleString()}</div>
                <div className="text-[11px] text-text-muted">recorded units</div>
              </div>
            ))}
          </div>
          <div className="overflow-x-auto bg-bg-card rounded-xl border border-border">
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
                {items.map((item, index) => (
                  <tr key={`${item.month}-${item.event_type}-${index}`} className="border-b border-border-light last:border-0">
                    <td className="px-4 py-3">{new Date(item.month).toLocaleDateString([], { year: 'numeric', month: 'long' })}</td>
                    <td className="px-4 py-3 capitalize">{item.event_type.replaceAll('_', ' ')}</td>
                    <td className="px-4 py-3">{Number(item.event_count).toLocaleString()}</td>
                    <td className="px-4 py-3">{Number(item.units).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <section className="bg-bg-card rounded-xl border border-border p-5">
        <h2 className="text-[14px] font-semibold">Subscription & invoices</h2>
        <p className="text-[12px] text-text-secondary mt-1">
          Online subscriptions, invoices, and payment methods are not available yet. Billing is planned for Phase 5; no payment method is stored or charged from this dashboard.
        </p>
      </section>
    </div>
  )
}
