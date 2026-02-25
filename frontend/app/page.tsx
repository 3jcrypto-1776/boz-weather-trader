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
import type { CityCode, DashboardData, DashboardStats, StatsPeriod } from "@/lib/types";
import { centsToDollars, confidenceBadgeColor, formatPnL, shortBracketLabel, CITY_NAMES } from "@/lib/utils";

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

// ─── Predictions Section ───

function formatMarketDate(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  const date = new Date(year, month - 1, day);
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

const PREDICTION_CITIES: CityCode[] = ["NYC", "CHI", "MIA", "AUS"];

function PredictionsSection({
  predictions,
}: {
  predictions: DashboardData["predictions"];
}) {
  const [selectedCity, setSelectedCity] = useState<CityCode>(
    predictions[0]?.city ?? "NYC",
  );

  const pred = predictions.find((p) => p.city === selectedCity);
  const dateLabel = predictions[0]?.date
    ? formatMarketDate(predictions[0].date)
    : "";

  // Cities that have predictions available
  const availableCities = new Set(predictions.map((p) => p.city));

  return (
    <section className="mb-6">
      {/* Title with market date */}
      <div className="flex items-baseline gap-2 mb-3">
        <h2 className="text-sm font-semibold text-gray-900">
          Predictions
        </h2>
        {dateLabel && (
          <span className="text-xs text-boz-neutral">for {dateLabel}</span>
        )}
      </div>

      {/* City toggle buttons */}
      <div className="flex bg-gray-100 rounded-lg p-0.5 mb-3">
        {PREDICTION_CITIES.filter((c) => availableCities.has(c)).map((city) => (
          <button
            key={city}
            onClick={() => setSelectedCity(city)}
            className={`flex-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              selectedCity === city
                ? "bg-white text-boz-primary shadow-sm"
                : "text-boz-neutral hover:text-gray-900"
            }`}
          >
            {CITY_NAMES[city]}
          </button>
        ))}
      </div>

      {/* Single city prediction chart */}
      {pred && <PredictionChart pred={pred} />}
    </section>
  );
}

function PredictionChart({
  pred,
}: {
  pred: DashboardData["predictions"][number];
}) {
  const peakBracket = pred.brackets.reduce((best, b) =>
    b.probability > best.probability ? b : best,
  );
  const peakPct = Math.round(peakBracket.probability * 100);
  const peakLabel = shortBracketLabel(
    peakBracket.bracket_label,
    peakBracket.lower_bound_f,
    peakBracket.upper_bound_f,
  );
  const maxProb = peakBracket.probability;

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium">
          {CITY_NAMES[pred.city]}
        </span>
        <span className="text-xs text-boz-neutral">
          Peak:{" "}
          <span className="text-boz-primary font-semibold">
            {peakLabel} ({peakPct}%)
          </span>
        </span>
      </div>

      {/* Horizontal bar chart */}
      <div className="space-y-1">
        {pred.brackets.map((b) => {
          const pct = Math.round(b.probability * 100);
          const isPeak = b === peakBracket;
          const barWidth =
            maxProb > 0 ? (b.probability / maxProb) * 100 : 0;
          const label = shortBracketLabel(
            b.bracket_label,
            b.lower_bound_f,
            b.upper_bound_f,
          );

          return (
            <div
              key={b.bracket_label}
              className="flex items-center gap-1.5"
              title={b.bracket_label}
            >
              <span
                className={`text-[11px] w-[50px] text-right shrink-0 ${
                  isPeak
                    ? "font-semibold text-boz-primary"
                    : "text-boz-neutral"
                }`}
              >
                {label}
              </span>
              <div className="flex-1 h-3.5 bg-gray-100 rounded-sm overflow-hidden">
                <div
                  className={`h-full rounded-sm ${
                    isPeak ? "bg-boz-primary" : "bg-blue-200"
                  }`}
                  style={{
                    width: `${Math.max(barWidth, 2)}%`,
                  }}
                />
              </div>
              <span
                className={`text-[11px] w-[30px] shrink-0 ${
                  isPeak
                    ? "font-semibold text-boz-primary"
                    : "text-boz-neutral"
                }`}
              >
                {pct}%
              </span>
            </div>
          );
        })}
      </div>

      {/* Footer: mean + confidence */}
      <div className="flex items-center justify-between mt-1.5 text-[10px] text-boz-neutral">
        <span>
          Mean {pred.ensemble_mean_f.toFixed(0)}°F ±
          {pred.ensemble_std_f.toFixed(1)}
        </span>
        <span className={`capitalize px-1.5 py-0.5 rounded-full ${confidenceBadgeColor(pred.confidence)}`}>
          {pred.confidence}
        </span>
      </div>
    </div>
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
        <PredictionsSection predictions={data.predictions} />
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
