/**
 * SWR hooks — typed data fetching hooks for each backend endpoint.
 *
 * SWR cache IS the global state. No Redux/Zustand needed.
 * Each hook has an appropriate refresh interval:
 *   - Dashboard: 30s (balance changes)
 *   - Markets: 60s (predictions update infrequently)
 *   - Queue: 10s (new trades appear)
 *   - Logs: 2s (real-time log viewer)
 *   - Trades/Settings/Performance: 0 (fetch on mount only)
 */

import useSWR, { type SWRConfiguration } from "swr";

import {
  fetchAuthStatus,
  fetchCalendar,
  fetchCalibration,
  fetchCurrentWeather,
  fetchDashboard,
  fetchLogs,
  fetchMarkets,
  fetchPendingTrades,
  fetchPerformance,
  fetchSettings,
  fetchSourceAccuracy,
  fetchTrades,
} from "./api";
import type {
  AuthStatusResponse,
  BracketPrediction,
  CalendarMonth,
  CalibrationReport,
  CityCode,
  CurrentWeatherResponse,
  DashboardData,
  LogEntry,
  PendingTrade,
  PerformanceData,
  SourceAccuracy,
  TradesPage,
  UserSettings,
} from "./types";

// ─── Auth Status ───

export function useAuthStatus(config?: SWRConfiguration) {
  return useSWR<AuthStatusResponse>(
    "/api/auth/status",
    () => fetchAuthStatus(),
    {
      refreshInterval: 0,
      ...config,
    }
  );
}

// ─── Dashboard ───

export function useDashboard(config?: SWRConfiguration) {
  return useSWR<DashboardData>(
    "/api/dashboard",
    () => fetchDashboard(),
    {
      refreshInterval: 30_000,
      ...config,
    }
  );
}

// ─── Markets ───

export function useMarkets(city?: CityCode, config?: SWRConfiguration) {
  return useSWR<BracketPrediction[]>(
    city ? `/api/markets?city=${city}` : "/api/markets",
    () => fetchMarkets(city),
    {
      refreshInterval: 60_000,
      ...config,
    }
  );
}

// ─── Pending Trades (Queue) ───

export function usePendingTrades(config?: SWRConfiguration) {
  return useSWR<PendingTrade[]>(
    "/api/queue",
    () => fetchPendingTrades(),
    {
      refreshInterval: 10_000,
      ...config,
    }
  );
}

// ─── Trades (paginated) ───

export function useTrades(
  page: number = 1,
  city?: CityCode,
  status?: string,
  date?: string,
  config?: SWRConfiguration
) {
  const params = new URLSearchParams({ page: String(page) });
  if (city) params.set("city", city);
  if (status) params.set("status", status);
  if (date) params.set("trade_date", date);

  return useSWR<TradesPage>(
    `/api/trades?${params.toString()}`,
    () => fetchTrades(page, city, status, date),
    {
      refreshInterval: 0,
      ...config,
    }
  );
}

// ─── Settings ───

export function useSettings(config?: SWRConfiguration) {
  return useSWR<UserSettings>(
    "/api/settings",
    () => fetchSettings(),
    {
      refreshInterval: 0,
      ...config,
    }
  );
}

// ─── Logs ───

export function useLogs(
  params?: { module?: string; level?: string; after?: string },
  config?: SWRConfiguration
) {
  const key = params
    ? `/api/logs?${new URLSearchParams(
        Object.entries(params).filter(([, v]) => v) as [string, string][]
      ).toString()}`
    : "/api/logs";

  return useSWR<LogEntry[]>(
    key,
    () => fetchLogs(params),
    {
      refreshInterval: 2_000,
      ...config,
    }
  );
}

// ─── Performance ───

export function usePerformance(config?: SWRConfiguration) {
  return useSWR<PerformanceData>(
    "/api/performance",
    () => fetchPerformance(),
    {
      refreshInterval: 0,
      ...config,
    }
  );
}

// ─── Accuracy / Calibration ───

export function useCalibration(
  city?: CityCode,
  config?: SWRConfiguration
) {
  const cityParam = city || "NYC";
  return useSWR<CalibrationReport>(
    `/api/accuracy/calibration?city=${cityParam}`,
    () => fetchCalibration(cityParam),
    { refreshInterval: 0, ...config }
  );
}

export function useSourceAccuracy(
  city?: CityCode,
  config?: SWRConfiguration
) {
  const cityParam = city || "NYC";
  return useSWR<SourceAccuracy[]>(
    `/api/accuracy/sources?city=${cityParam}`,
    () => fetchSourceAccuracy(cityParam),
    { refreshInterval: 0, ...config }
  );
}

// ─── Current Weather ───

export function useCurrentWeather(config?: SWRConfiguration) {
  return useSWR<CurrentWeatherResponse>(
    "/api/weather/current",
    () => fetchCurrentWeather(),
    {
      refreshInterval: 300_000, // 5 minutes — matches backend cache TTL
      ...config,
    }
  );
}

// ─── Calendar ───

export function useCalendar(
  year: number,
  month: number,
  config?: SWRConfiguration
) {
  return useSWR<CalendarMonth>(
    `/api/trades/calendar?year=${year}&month=${month}`,
    () => fetchCalendar(year, month),
    { refreshInterval: 0, ...config }
  );
}
