import useSWR from 'swr'

export function usePolling<T>(key: string | null, fetcher: () => Promise<T>, interval = 3000) {
  return useSWR(key, fetcher, {
    refreshInterval: interval,
    revalidateOnFocus: true,
    errorRetryCount: 3,
  })
}
