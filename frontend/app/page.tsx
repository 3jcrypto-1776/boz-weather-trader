"use client";

import {
  Activity,
  DollarSign,
  TrendingDown,
  TrendingUp,
  Trophy,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import ErrorBoundary from "@/components/ui/error-boundary";
import Skeleton from "@/components/ui/skeleton";
import TradeCard from "@/components/trade-card/trade-card";
import WeatherTicker from "@/components/weather-ticker/weather-ticker";
import { useDashboard, useDashboardStats } from "@/lib/hooks";
import { groupByMarket } from "@/lib/trade-grouping";
import type { DashboardData, DashboardStats, StatsPeriod } from "@/lib/types";
import { centsToDollars, formatPnL, CITY_NAMES } from "@/lib/utils";

// ─── Period Toggle Helpers ───

const PNL_CYCLE: StatsPeriod[] = ["week", "yesterday", "month", "year", "all_time"];
const WL_CYCLE: StatsPeriod[] = ["all_time", "yesterday", "week", "month", "year"];

const PERIOD_PNL_LABELS: Record<StatsPeriod, string> = {
  yesterday: "Yesterday P&L",
  week: "Weekly P&L",
  month: "Monthly P&L",
  year: "Yearly P&L",
  all_time: "All-Time P&L",
};

const PERIOD_WL_LABELS: Record<StatsPeriod, string> = {
  yesterday: "Yesterday W/L",
  week: "Weekly W/L",
  month: "Monthly W/L",
  year: "Yearly W/L",
  all_time: "All-Time W/L",
};

function nextPeriod(current: StatsPeriod, cycle: StatsPeriod[]): StatsPeriod {
  const idx = cycle.indexOf(current);
  return cycle[(idx + 1) % cycle.length];
}

// ─── Stat Cards ───

function StatCard({
  label,
  value,
  icon: Icon,
  color = "text-gray-900",
  onClick,
}: {
  label: string;
  value: string;
  icon: React.ElementType;
  color?: string;
  onClick?: () => void;
}) {
  const Wrapper = onClick ? "button" : "div";
  return (
    <Wrapper
      className={`bg-white rounded-lg border border-gray-200 shadow-sm p-4 text-left w-full ${onClick ? "cursor-pointer hover:border-boz-primary transition-colors" : ""}`}
      onClick={onClick}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon size={16} className="text-boz-neutral" />
        <span className="text-xs text-boz-neutral">{label}</span>
      </div>
      <span className={`text-lg font-bold ${color}`}>{value}</span>
    </Wrapper>
  );
}

// ─── Dashboard Content ───

function DashboardContent({
  data,
  stats,
}: {
  data: DashboardData;
  stats: DashboardStats | undefined;
}) {
  const router = useRouter();

  // P/L period toggle (defaults to "week")
  const [pnlPeriod, setPnlPeriod] = useState<StatsPeriod>("week");
  const handlePnlClick = useCallback(() => {
    setPnlPeriod((p) => nextPeriod(p, PNL_CYCLE));
  }, []);

  // W/L period toggle (defaults to "all_time")
  const [wlPeriod, setWlPeriod] = useState<StatsPeriod>("all_time");
  const handleWlClick = useCallback(() => {
    setWlPeriod((p) => nextPeriod(p, WL_CYCLE));
  }, []);

  // Compute P/L value and color from stats
  const pnlCents = stats ? stats[pnlPeriod].pnl_cents : data.today_pnl_cents;
  const pnlColor = pnlCents >= 0 ? "text-boz-success" : "text-boz-danger";
  const PnlIcon = pnlCents >= 0 ? TrendingUp : TrendingDown;

  // Compute W/L record from stats
  const wlWins = stats ? stats[wlPeriod].wins : 0;
  const wlLosses = stats ? stats[wlPeriod].losses : 0;
  const wlValue = stats ? `${wlWins}W / ${wlLosses}L` : "—";

  const positionMarkets = useMemo(
    () => groupByMarket(data.active_positions),
    [data.active_positions],
  );
  const recentMarkets = useMemo(
    () => groupByMarket(data.recent_trades),
    [data.recent_trades],
  );

  return (
    <>
      {/* Stats Grid */}
      <div className="grid grid-cols-2 gap-3 mb-6">
        <StatCard
          label="Balance"
          value={`$${centsToDollars(data.balance_cents)}`}
          icon={DollarSign}
        />
        <StatCard
          label={PERIOD_PNL_LABELS[pnlPeriod]}
          value={formatPnL(pnlCents)}
          icon={PnlIcon}
          color={pnlColor}
          onClick={handlePnlClick}
        />
        <StatCard
          label="Open Positions"
          value={String(data.active_positions.length)}
          icon={Activity}
          onClick={() => router.push("/trades")}
        />
        <StatCard
          label={PERIOD_WL_LABELS[wlPeriod]}
          value={wlValue}
          icon={Trophy}
          onClick={handleWlClick}
        />
      </div>

      {/* Predictions Summary */}
      {data.predictions.length > 0 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">
            Today&apos;s Predictions
          </h2>
          <div className="space-y-2">
            {data.predictions.map((pred) => (
              <div
                key={pred.city}
                className="bg-white rounded-lg border border-gray-200 shadow-sm p-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">
                    {CITY_NAMES[pred.city]}
                  </span>
                  <span className="text-xs text-boz-neutral">
                    {pred.ensemble_mean_f.toFixed(0)}°F ±
                    {pred.ensemble_std_f.toFixed(1)}
                  </span>
                </div>
                <div className="flex gap-1 mt-2">
                  {pred.brackets.map((b) => (
                    <div
                      key={b.bracket_label}
                      className="flex-1 text-center"
                      title={b.bracket_label}
                    >
                      <div
                        className="bg-boz-primary rounded-sm mx-px"
                        style={{
                          height: `${Math.max(b.probability * 80, 4)}px`,
                        }}
                      />
                      <span className="text-[9px] text-boz-neutral leading-tight block mt-0.5">
                        {Math.round(b.probability * 100)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Active Positions */}
      {positionMarkets.length > 0 && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">
            Open Positions
          </h2>
          <div className="space-y-4">
            {positionMarkets.map((market) => (
              <div key={market.marketKey}>
                <h3 className="text-xs font-medium text-boz-neutral mb-2">
                  {market.label}
                </h3>
                <div className="space-y-2">
                  {market.groups.map((group) => (
                    <TradeCard key={group.groupKey} group={group} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Recent Trades */}
      {recentMarkets.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-900 mb-3">
            Recent Trades
          </h2>
          <div className="space-y-4">
            {recentMarkets.map((market) => (
              <div key={market.marketKey}>
                <h3 className="text-xs font-medium text-boz-neutral mb-2">
                  {market.label}
                </h3>
                <div className="space-y-2">
                  {market.groups.map((group) => (
                    <TradeCard key={group.groupKey} group={group} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function DashboardSkeleton() {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 mb-6">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
      <Skeleton className="h-6 w-40 mb-3" />
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    </>
  );
}

export default function DashboardPage() {
  const { data, error, isLoading } = useDashboard();
  const { data: stats } = useDashboardStats();

  return (
    <ErrorBoundary>
      <h1 className="text-xl font-bold mb-4">Dashboard</h1>
      <WeatherTicker />

      {isLoading && <DashboardSkeleton />}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-boz-danger">
          {error.message || "Unable to connect to server"}
        </div>
      )}

      {data && <DashboardContent data={data} stats={stats} />}
    </ErrorBoundary>
  );
}
