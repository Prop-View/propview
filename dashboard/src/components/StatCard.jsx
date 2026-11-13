export default function StatCard({ icon: Icon, label, value, sub, accent }) {
  return (
    <div className="bg-bg-card rounded-xl border border-border p-4 flex items-start gap-3">
      <div
        className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
          accent ? 'bg-accent/10 text-accent' : 'bg-border-light text-text-secondary'
        }`}
      >
        <Icon size={18} strokeWidth={1.75} />
      </div>
      <div className="min-w-0">
        <div className="text-[12px] text-text-muted font-medium uppercase tracking-wide">
          {label}
        </div>
        <div className="text-[22px] font-semibold tracking-[-0.02em] text-text leading-tight mt-0.5">
          {value}
        </div>
        {sub && (
          <div className="text-[12px] text-text-secondary mt-0.5">{sub}</div>
        )}
      </div>
    </div>
  )
}
