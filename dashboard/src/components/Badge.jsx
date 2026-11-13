const styles = {
  high: 'bg-red-50 text-red-600 border-red-100',
  medium: 'bg-amber-50 text-amber-600 border-amber-100',
  low: 'bg-blue-50 text-blue-600 border-blue-100',
  booked: 'bg-green-50 text-green-600 border-green-100',
  qualified: 'bg-purple-50 text-purple-600 border-purple-100',
  transferred: 'bg-orange-50 text-orange-600 border-orange-100',
  nurture: 'bg-sky-50 text-sky-600 border-sky-100',
  dropped: 'bg-stone-100 text-stone-500 border-stone-200',
  scheduled: 'bg-blue-50 text-blue-600 border-blue-100',
  confirmed: 'bg-green-50 text-green-600 border-green-100',
  completed: 'bg-stone-100 text-stone-500 border-stone-200',
  no_show: 'bg-red-50 text-red-600 border-red-100',
  cancelled: 'bg-stone-100 text-stone-500 border-stone-200',
  active: 'bg-green-50 text-green-600 border-green-100',
  pending: 'bg-amber-50 text-amber-600 border-amber-100',
  sold: 'bg-stone-100 text-stone-500 border-stone-200',
  off_market: 'bg-stone-100 text-stone-500 border-stone-200',
  new: 'bg-blue-50 text-blue-600 border-blue-100',
  appointment_set: 'bg-green-50 text-green-600 border-green-100',
  closed_won: 'bg-emerald-50 text-emerald-600 border-emerald-100',
  closed_lost: 'bg-stone-100 text-stone-500 border-stone-200',
}

const labels = {
  no_show: 'No Show',
  off_market: 'Off Market',
  appointment_set: 'Appt Set',
  closed_won: 'Won',
  closed_lost: 'Lost',
}

export default function Badge({ variant }) {
  if (!variant) return null
  const cls = styles[variant] || 'bg-stone-100 text-stone-500 border-stone-200'
  const label = labels[variant] || variant.charAt(0).toUpperCase() + variant.slice(1)
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold border ${cls}`}>
      {label}
    </span>
  )
}
