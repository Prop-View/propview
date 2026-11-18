import { Bath, BedDouble, Building2, Maximize2, Search, Upload } from 'lucide-react'
import { useState } from 'react'
import { api, getAuth } from '../api'
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
  const canManage = getAuth().user?.role === 'owner'
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [uploading, setUploading] = useState(false)
  const [uploadMessage, setUploadMessage] = useState('')
  const [editValues, setEditValues] = useState({})
  const [busyId, setBusyId] = useState(null)

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

  async function uploadCsv(event) {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadMessage('')
    try {
      const result = await api.uploadListings(file)
      setUploadMessage(`Imported ${result.inserted} listings.`)
      refetch()
    } catch (requestError) {
      setUploadMessage(`Upload failed: ${requestError.message}`)
    } finally {
      setUploading(false)
      event.target.value = ''
    }
  }

  async function saveProperty(property) {
    const changes = editValues[property.id] || {}
    if (!Object.keys(changes).length) return
    setBusyId(property.id)
    setUploadMessage('')
    try {
      await api.updateProperty(property.id, changes)
      setEditValues((current) => {
        const next = { ...current }
        delete next[property.id]
        return next
      })
      setUploadMessage('Listing updated.')
      refetch()
    } catch (requestError) {
      setUploadMessage(`Update failed: ${requestError.message}`)
    } finally {
      setBusyId(null)
    }
  }

  async function deleteProperty(property) {
    if (!window.confirm(`Delete the listing at ${property.address}? This cannot be undone.`)) return
    setBusyId(property.id)
    setUploadMessage('')
    try {
      await api.deleteProperty(property.id)
      setUploadMessage('Listing deleted.')
      refetch()
    } catch (requestError) {
      setUploadMessage(`Delete failed: ${requestError.message}`)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-5 max-w-[1200px]">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Properties</h1>
        <p className="text-[13px] text-text-secondary mt-0.5">
          {data ? `${data.total} listings managed by this agency` : 'Loading properties...'}
        </p>
      </div>

      {canManage && <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent text-white text-[12px] font-medium cursor-pointer">
          <Upload size={14} />
          {uploading ? 'Uploading...' : 'Upload listings CSV'}
          <input type="file" accept=".csv,text/csv" className="sr-only" disabled={uploading} onChange={uploadCsv} />
        </label>
        <a href="/listings-template.csv" download className="text-[12px] text-accent hover:underline">Download CSV template</a>
        {uploadMessage && <span role="status" className={`text-[12px] ${uploadMessage.includes('failed') ? 'text-hot' : 'text-text-secondary'}`}>{uploadMessage}</span>}
      </div>}
      {!canManage && uploadMessage && <p role="status" className="text-[12px] text-text-secondary">{uploadMessage}</p>}

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
                {canManage && <details className="mt-4 border-t border-border-light pt-3">
                  <summary className="text-[12px] text-accent cursor-pointer">Edit listing</summary>
                  <div className="grid grid-cols-2 gap-3 mt-3">
                    <label className="text-[11px] text-text-muted">
                      Price
                      <input
                        type="number"
                        min="0"
                        value={editValues[prop.id]?.price ?? prop.price}
                        onChange={(event) => setEditValues((current) => ({
                          ...current,
                          [prop.id]: { ...current[prop.id], price: Number(event.target.value) },
                        }))}
                        className="w-full mt-1 px-2 py-1.5 rounded border border-border text-[12px] text-text"
                      />
                    </label>
                    <label className="text-[11px] text-text-muted">
                      Status
                      <select
                        value={editValues[prop.id]?.status ?? prop.status}
                        onChange={(event) => setEditValues((current) => ({
                          ...current,
                          [prop.id]: { ...current[prop.id], status: event.target.value },
                        }))}
                        className="w-full mt-1 px-2 py-1.5 rounded border border-border bg-bg-card text-[12px] text-text"
                      >
                        {['active', 'pending', 'sold', 'off_market'].map((status) => <option key={status} value={status}>{status.replaceAll('_', ' ')}</option>)}
                      </select>
                    </label>
                  </div>
                  <div className="flex justify-between mt-3">
                    <button type="button" disabled={busyId === prop.id} onClick={() => deleteProperty(prop)} className="text-[12px] text-hot">Delete</button>
                    <button type="button" disabled={busyId === prop.id} onClick={() => saveProperty(prop)} className="px-3 py-1.5 rounded bg-accent text-white text-[11px] disabled:opacity-50">
                      {busyId === prop.id ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                </details>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
