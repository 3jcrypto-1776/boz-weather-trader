"use client";

import {
  BarChart3,
  Calendar,
  ChevronLeft,
  ChevronRight,
  List,
  RefreshCw,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import CalendarGrid from "@/components/calendar/calendar-grid";
import DayDetailPanel from "@/components/calendar/day-detail-panel";
import TradeCard from "@/components/trade-card/trade-card";
import EmptyState from "@/components/ui/empty-state";
import ErrorBoundary from "@/components/ui/error-boundary";
import Skeleton from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { syncTrades } from "@/lib/api";
import WeatherTicker from "@/components/weather-ticker/weather-ticker";
import { useCalendar, useTrades } from "@/lib/hooks";
import { groupByMarket } from "@/lib/trade-grouping";
import type { CityCode, SyncResult, TradeStatus } from "@/lib/types";
import { formatPnL, formatProbability } from "@/lib/utils";

type ViewTab = "calendar" | "history";

const CITY_OPTIONS: (CityCode | "ALL")[] = ["ALL", "NYC", "CHI", "MIA", "AUS"];
const STATUS_OPTIONS: (TradeStatus | "ALL")[] = [
  "ALL",
  "OPEN",
  "WON",
  "LOST",
  "CANCELED",
];

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// ─── Calendar Tab ───

function CalendarView() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const { data, isLoading, error } = useCalendar(year, month);

  const goToPrevMonth = useCallback(() => {
    setSelectedDate(null);
    if (month === 1) {
      setMonth(12);
      setYear((y) => y - 1);
    } else {
      setMonth((m) => m - 1);
    }
  }, [month]);

  const goToNextMonth = useCallback(() => {
    setSelectedDate(null);
    if (month === 12) {
      setMonth(1);
      setYear((y) => y + 1);
    } else {
      setMonth((m) => m + 1);
    }
  }, [month]);

  const goToThisMonth = useCallback(() => {
    setSelectedDate(null);
    const n = new Date();
    setYear(n.getFullYear());
    setMonth(n.getMonth() + 1);
  }, []);

  const handleDayClick = useCallback((date: string) => {
    setSelectedDate((prev) => (prev === date ? null : date));
  }, []);

  const selectedDayStats = useMemo(() => {
    if (!selectedDate || !data) return null;
    return data.days.find((d) => d.date === selectedDate) ?? null;
  }, [selectedDate, data]);

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-10" />
        <Skeleton className="h-[400px]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-boz-danger">
        {error.message || "Unable to load calendar data"}
      </div>
    );
  }

  return (
    <div>
      {/* Month Navigation */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <button
            onClick={goToPrevMonth}
            className="min-h-[36px] min-w-[36px] flex items-center justify-center rounded-lg border border-gray-200 hover:bg-gray-50"
          >
            <ChevronLeft size={16} />
          </button>
          <h2 className="text-sm font-bold min-w-[140px] text-center">
            {MONTH_NAMES[month - 1]} {year}
          </h2>
          <button
            onClick={goToNextMonth}
            className="min-h-[36px] min-w-[36px] flex items-center justify-center rounded-lg border border-gray-200 hover:bg-gray-50"
          >
            <ChevronRight size={16} />
          </button>
          <button
            onClick={goToThisMonth}
            className="min-h-[36px] px-3 py-1.5 rounded-lg text-xs font-medium bg-white border border-gray-200 text-boz-neutral hover:bg-gray-50 ml-1"
          >
            This month
          </button>
        </div>
      </div>

      {/* Monthly Summary Bar */}
      {data && data.total_trades > 0 && (
        <div className="flex flex-wrap gap-4 mb-3 text-xs bg-white rounded-lg border border-gray-200 px-4 py-2.5">
          <span className="text-boz-neutral">Monthly stats:</span>
          <span
            className={`font-bold ${
              data.total_pnl_cents >= 0
                ? "text-boz-success"
                : "text-boz-danger"
            }`}
          >
            {formatPnL(data.total_pnl_cents)}
          </span>
          <span className="text-boz-neutral">
            {data.total_trades} trades
          </span>
          <span className="text-boz-neutral">
            {data.total_wins}W / {data.total_losses}L
          </span>
          {data.total_trades > 0 && (
            <span className="text-boz-neutral">
              {formatProbability(data.total_wins / data.total_trades)} win rate
            </span>
          )}
          <span className="text-boz-neutral">
            {data.trading_days} trading day{data.trading_days !== 1 ? "s" : ""}
          </span>
        </div>
      )}

      {/* Calendar Grid */}
      <CalendarGrid
        year={year}
        month={month}
        days={data?.days ?? []}
        onDayClick={handleDayClick}
        selectedDate={selectedDate}
      />

      {/* Weekly Summaries */}
      {data && data.weeks.length > 0 && (
        <div className="mt-3 grid grid-cols-2 lg:grid-cols-4 gap-2">
          {data.weeks.map((week, idx) => (
            <div
              key={week.week_number}
              className="bg-white rounded-lg border border-gray-200 px-3 py-2"
            >
              <span className="text-[10px] text-boz-neutral">
                Week {idx + 1}
              </span>
              <div
                className={`text-sm font-bold ${
                  week.pnl_cents >= 0 ? "text-boz-success" : "text-boz-danger"
                }`}
              >
                {formatPnL(week.pnl_cents)}
              </div>
              <span className="text-[10px] text-boz-neutral">
                {week.trading_days} day{week.trading_days !== 1 ? "s" : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Day Detail Panel */}
      {selectedDate && selectedDayStats && (
        <DayDetailPanel
          date={selectedDate}
          dayStats={selectedDayStats}
          onClose={() => setSelectedDate(null)}
        />
      )}
    </div>
  );
}

// ─── History Tab (existing trade list) ───

function HistoryView() {
  const [page, setPage] = useState(1);
  const [cityFilter, setCityFilter] = useState<CityCode | "ALL">("ALL");
  const [statusFilter, setStatusFilter] = useState<TradeStatus | "ALL">("ALL");
  const [syncing, setSyncing] = useState(false);

  const city = cityFilter === "ALL" ? undefined : cityFilter;
  const status = statusFilter === "ALL" ? undefined : statusFilter;
  const {
    data,
    error,
    isLoading,
    mutate: mutateTrades,
  } = useTrades(page, city, status);
  const { showToast } = useToast();

  const totalPages = data ? Math.ceil(data.total / 20) : 0;

  const trades = data?.trades;
  const markets = useMemo(() => groupByMarket(trades ?? []), [trades]);

  const totalPnl = (trades ?? []).reduce(
    (sum, t) => sum + (t.pnl_cents ?? 0),
    0
  );
  const wonCount = (trades ?? []).filter((t) => t.status === "WON").length;
  const lostCount = (trades ?? []).filter((t) => t.status === "LOST").length;

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      const result: SyncResult = await syncTrades();
      if (result.synced_count > 0) {
        showToast({
          variant: "success",
          title: "Portfolio synced",
          message: `Synced ${result.synced_count} trade${result.synced_count > 1 ? "s" : ""} from Kalshi`,
        });
        await mutateTrades();
      } else {
        showToast({
          variant: "info",
          title: "Already in sync",
          message: "No new trades found on Kalshi",
        });
      }
    } catch (err) {
      showToast({
        variant: "warning",
        title: "Sync failed",
        message:
          err instanceof Error ? err.message : "Unable to sync with Kalshi",
      });
    } finally {
      setSyncing(false);
    }
  }, [mutateTrades, showToast]);

  return (
    <>
      {/* Sync button */}
      <div className="flex justify-end mb-3">
        <button
          onClick={handleSync}
          disabled={syncing}
          className="min-h-[36px] px-3 py-1.5 rounded-lg text-xs font-medium bg-boz-primary text-white hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5 transition-colors"
        >
          <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
          {syncing ? "Syncing..." : "Sync from Kalshi"}
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-4">
        <div className="flex gap-1">
          {CITY_OPTIONS.map((c) => (
            <button
              key={c}
              onClick={() => {
                setCityFilter(c);
                setPage(1);
              }}
              className={`min-h-[36px] px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                cityFilter === c
                  ? "bg-boz-primary text-white"
                  : "bg-white border border-gray-200 text-boz-neutral hover:bg-gray-50"
              }`}
            >
              {c === "ALL" ? "All" : c}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          {STATUS_OPTIONS.map((s) => (
            <button
              key={s}
              onClick={() => {
                setStatusFilter(s);
                setPage(1);
              }}
              className={`min-h-[36px] px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                statusFilter === s
                  ? "bg-boz-primary text-white"
                  : "bg-white border border-gray-200 text-boz-neutral hover:bg-gray-50"
              }`}
            >
              {s === "ALL" ? "All" : s}
            </button>
          ))}
        </div>
      </div>

      {/* Summary stats */}
      {data && data.total > 0 && (
        <div className="flex gap-4 mb-4 text-xs">
          <span className="text-boz-neutral">{data.total} total trades</span>
          {wonCount > 0 && (
            <span className="text-boz-success font-medium">{wonCount} won</span>
          )}
          {lostCount > 0 && (
            <span className="text-boz-danger font-medium">
              {lostCount} lost
            </span>
          )}
          <span
            className={`font-medium ${
              totalPnl >= 0 ? "text-boz-success" : "text-boz-danger"
            }`}
          >
            Page P&L: {formatPnL(totalPnl)}
          </span>
        </div>
      )}

      {/* Content */}
      {isLoading && (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-boz-danger">
          {error.message || "Unable to load trades"}
        </div>
      )}

      {data && data.trades.length === 0 && (
        <EmptyState
          icon={BarChart3}
          title="No Trades Found"
          description="Your trade history will appear here once you start trading."
        />
      )}

      {data && data.trades.length > 0 && (
        <>
          <div className="space-y-4 mb-4">
            {markets.map((market) => (
              <section key={market.marketKey}>
                <h2 className="text-sm font-semibold text-gray-900 mb-2">
                  {market.label}
                </h2>
                <div className="space-y-2">
                  {market.groups.map((group) => (
                    <TradeCard key={group.groupKey} group={group} />
                  ))}
                </div>
              </section>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft size={16} />
              </button>
              <span className="text-sm text-boz-neutral px-2">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}

// ─── Main Trades Page ───

export default function TradesPage() {
  const [activeTab, setActiveTab] = useState<ViewTab>("calendar");

  return (
    <ErrorBoundary>
      {/* Header with tabs */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">Trades</h1>

        {/* View tabs */}
        <div className="flex bg-gray-100 rounded-lg p-0.5">
          <button
            onClick={() => setActiveTab("calendar")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              activeTab === "calendar"
                ? "bg-white text-boz-primary shadow-sm"
                : "text-boz-neutral hover:text-gray-900"
            }`}
          >
            <Calendar size={14} />
            Calendar
          </button>
          <button
            onClick={() => setActiveTab("history")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              activeTab === "history"
                ? "bg-white text-boz-primary shadow-sm"
                : "text-boz-neutral hover:text-gray-900"
            }`}
          >
            <List size={14} />
            History
          </button>
        </div>
      </div>
      <WeatherTicker />

      {/* Tab content */}
      {activeTab === "calendar" ? <CalendarView /> : <HistoryView />}
    </ErrorBoundary>
  );
}
