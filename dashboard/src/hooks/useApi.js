import { useCallback, useEffect, useState } from 'react'

export default function useApi(fetchFn, deps = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refetch = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchFn()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, deps)

  useEffect(() => {
    refetch()
  }, [refetch])

  return { data, loading, error, refetch }
}
