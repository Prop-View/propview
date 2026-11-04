export default function EmptyState({ icon: Icon, title, description }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      {Icon && <Icon size={28} className="text-text-muted mb-3" />}
      <p className="text-[14px] font-medium text-text-secondary">{title}</p>
      {description && (
        <p className="text-[12px] text-text-muted mt-1 max-w-xs">{description}</p>
      )}
    </div>
  )
}
