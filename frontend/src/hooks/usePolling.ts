"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface UsePollingResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
  lastUpdated: Date | null;
}

export function usePolling<T>(
  fetchFn: () => Promise<T>,
  intervalMs: number
): UsePollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  const isMountedRef = useRef(true);

  const execute = useCallback(async () => {
    try {
      const result = await fetchFnRef.current();
      if (isMountedRef.current) {
        setData(result);
        setError(null);
        setLastUpdated(new Date());
      }
    } catch (err) {
      if (isMountedRef.current) {
        setError(err instanceof Error ? err.message : "Unknown error");
      }
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    execute();

    const timerId = setInterval(execute, intervalMs);

    return () => {
      isMountedRef.current = false;
      clearInterval(timerId);
    };
  }, [execute, intervalMs]);

  useEffect(() => {
    setLoading(true);
    execute();
  }, [fetchFn, execute]);

  return { data, loading, error, refetch: execute, lastUpdated };
}
