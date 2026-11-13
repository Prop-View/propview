import { Bath, BedDouble, Building2, Maximize2, Search } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import Loading from '../components/Loading'
import useApi from '../hooks/useApi'

function formatPrice(n) {
  if (!n) return '—'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  return `$${(n / 1_000).toFixed(0)}K`
}

export default function Properties() {
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')

  const params = {}
  if (typeFilter !== 'all') params.property_type = typeFilter
  const { data, loading, error, refetch } = useApi(
    () => api.listProperties({ limit: 100, ...params }),
    [typeFilter]
  )

  const properties = (data?.items || []).filter(
    (p) =>
      !search ||
      p.address?.toLowerCase().includes(search.toLowerCase()) ||
      p.city?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="space-y-5 max-w-[1200px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Properties</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          {data ? `${data.total} listings managed by this agency` : 'Loading properties...'}
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <div className="relative flex-1 max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            placeholder="Search properties..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-bg-card text-[13px] outline-none focus:border-accent transition-colors"
          />
        </div>
        <div className="flex gap-1.5">
          {['all', 'house', 'condo', 'townhouse', 'land'].map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-3 py-1.5 rounded-lg text-[12px] font-medium transition-colors ${
                typeFilter === t
                  ? 'bg-text text-white'
                  : 'bg-bg-card border border-border text-text-secondary hover:text-text'
              }`}
            >
              {t === 'all' ? 'All' : t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error} onRetry={refetch} />
      ) : properties.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No properties found"
          description={search || typeFilter !== 'all' ? 'Try adjusting your filters' : 'Upload listings via the Admin API to see them here.'}
        />
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {properties.map((prop) => (
            <div
              key={prop.id}
              className="bg-bg-card rounded-xl border border-border overflow-hidden hover:shadow-sm transition-shadow"
            >
              <div className="h-36 bg-gradient-to-br from-stone-100 to-stone-50 flex items-center justify-center">
                <Building2 size={32} className="text-stone-300" />
              </div>
              <div className="p-4">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="text-[14px] font-semibold leading-tight">{prop.address}</h3>
                    <p className="text-[12px] text-text-muted mt-0.5">
                      {prop.city}, {prop.state}
                    </p>
                  </div>
                  <Badge variant={prop.status} />
                </div>

                <div className="text-[20px] font-semibold text-accent mt-3">
                  {formatPrice(prop.price)}
                </div>

                <div className="flex items-center gap-4 mt-3 pt-3 border-t border-border-light text-[12px] text-text-secondary">
                  {prop.beds != null && (
                    <span className="flex items-center gap-1">
                      <BedDouble size={13} /> {prop.beds} bed
                    </span>
                  )}
                  {prop.baths != null && (
                    <span className="flex items-center gap-1">
                      <Bath size={13} /> {prop.baths} bath
                    </span>
                  )}
                  {prop.sqft != null && (
                    <span className="flex items-center gap-1">
                      <Maximize2 size={13} /> {prop.sqft.toLocaleString()} sqft
                    </span>
                  )}
                </div>

                {prop.listing_agent && (
                  <div className="text-[11px] text-text-muted mt-2">
                    Agent: {prop.listing_agent}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
