import { AlertTriangle, RefreshCw } from 'lucide-react'

export default function ErrorState({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <AlertTriangle size={28} className="text-warm mb-3" />
      <p className="text-[13px] text-text-secondary mb-3">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-bg-card border border-border text-[12px] text-text-secondary hover:text-text transition-colors"
        >
          <RefreshCw size={13} /> Retry
        </button>
      )}
    </div>
  )
}
