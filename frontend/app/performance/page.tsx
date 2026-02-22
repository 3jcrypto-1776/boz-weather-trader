"use client";

import { useState } from "react";
import { BarChart3 } from "lucide-react";

import CalibrationChart from "@/components/charts/calibration-chart";
import CityPerformanceChart from "@/components/charts/city-performance-chart";
import PnlChart from "@/components/charts/pnl-chart";
import SourceAccuracyChart from "@/components/charts/source-accuracy-chart";
import EmptyState from "@/components/ui/empty-state";
import ErrorBoundary from "@/components/ui/error-boundary";
import Skeleton from "@/components/ui/skeleton";
import {
  useCalibration,
  usePerformance,
  useSourceAccuracy,
} from "@/lib/hooks";
import type { CityCode } from "@/lib/types";
import { centsToDollars, formatPnL, formatProbability } from "@/lib/utils";

const CITY_OPTIONS: CityCode[] = ["NYC", "CHI", "MIA", "AUS"];

export default function PerformancePage() {
  const { data, error, isLoading } = usePerformance();
  const [accuracyCity, setAccuracyCity] = useState<CityCode>("NYC");
  const { data: calibration } = useCalibration(accuracyCity);
  const { data: sources } = useSourceAccuracy(accuracyCity);

  if (isLoading) {
    return (
      <div>
        <h1 className="text-xl font-bold mb-4">Performance</h1>
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <h1 className="text-xl font-bold mb-4">Performance</h1>
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-boz-danger">
          {error.message || "Unable to load performance data"}
        </div>
      </div>
    );
  }

  if (!data || data.total_trades === 0) {
    return (
      <div>
        <h1 className="text-xl font-bold mb-4">Performance</h1>
        <EmptyState
          icon={BarChart3}
          title="No Performance Data"
          description="Performance metrics will appear after your first settled trades."
        />
      </div>
    );
  }

  // Compute ROI per city
  const roiByCity: Record<string, number | null> = {};
  for (const city of Object.keys(data.pnl_by_city)) {
    const cost = data.cost_by_city?.[city];
    if (cost && cost > 0) {
      roiByCity[city] = (data.pnl_by_city[city] / cost) * 100;
    } else {
      roiByCity[city] = null;
    }
  }

  return (
    <ErrorBoundary>
      <h1 className="text-xl font-bold mb-4">Performance</h1>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
          <span className="text-xs text-boz-neutral">Total Trades</span>
          <div className="text-lg font-bold">{data.total_trades}</div>
          <span className="text-xs text-boz-neutral">
            {data.wins}W / {data.losses}L
          </span>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
          <span className="text-xs text-boz-neutral">Win Rate</span>
          <div className="text-lg font-bold text-boz-primary">
            {formatProbability(data.win_rate)}
          </div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
          <span className="text-xs text-boz-neutral">Total P&L</span>
          <div
            className={`text-lg font-bold ${
              data.total_pnl_cents >= 0
                ? "text-boz-success"
                : "text-boz-danger"
            }`}
          >
            {formatPnL(data.total_pnl_cents)}
          </div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
          <span className="text-xs text-boz-neutral">Best / Worst</span>
          <div className="text-sm">
            <span className="text-boz-success font-medium">
              {formatPnL(data.best_trade_pnl_cents)}
            </span>
            {" / "}
            <span className="text-boz-danger font-medium">
              {formatPnL(data.worst_trade_pnl_cents)}
            </span>
          </div>
        </div>
        {calibration?.brier_score !== undefined &&
          calibration?.brier_score !== null && (
            <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
              <span className="text-xs text-boz-neutral">Brier Score</span>
              <div
                className={`text-lg font-bold ${
                  calibration.brier_score <= 0.15
                    ? "text-boz-success"
                    : calibration.brier_score <= 0.25
                      ? "text-yellow-600"
                      : "text-boz-danger"
                }`}
              >
                {calibration.brier_score.toFixed(3)}
              </div>
              <span className="text-xs text-boz-neutral">
                {calibration.brier_score <= 0.15
                  ? "Excellent"
                  : calibration.brier_score <= 0.25
                    ? "Good"
                    : "Needs work"}
              </span>
            </div>
          )}
      </div>

      {/* Charts */}
      <div className="space-y-4">
        <PnlChart data={data.cumulative_pnl} />
        <CityPerformanceChart pnlByCity={data.pnl_by_city} />

        {/* ROI by City */}
        {Object.keys(roiByCity).length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
            <h3 className="text-sm font-semibold mb-3">ROI by City</h3>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {Object.entries(roiByCity).map(([city, roi]) => (
                <div
                  key={city}
                  className="text-center p-3 bg-gray-50 rounded-lg"
                >
                  <span className="text-xs font-semibold text-boz-neutral">
                    {city}
                  </span>
                  {roi !== null ? (
                    <div
                      className={`text-lg font-bold ${
                        roi >= 0 ? "text-boz-success" : "text-boz-danger"
                      }`}
                    >
                      {roi >= 0 ? "+" : ""}
                      {roi.toFixed(1)}%
                    </div>
                  ) : (
                    <div className="text-sm text-boz-neutral">N/A</div>
                  )}
                  <span className="text-[10px] text-boz-neutral">
                    P&L: {formatPnL(data.pnl_by_city[city] || 0)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Accuracy Section with City Tabs */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">Model Accuracy</h3>
            <div className="flex gap-1 ml-auto">
              {CITY_OPTIONS.map((city) => (
                <button
                  key={city}
                  onClick={() => setAccuracyCity(city)}
                  className={`px-2 py-1 text-xs rounded-md font-medium transition-colors ${
                    accuracyCity === city
                      ? "bg-boz-primary text-white"
                      : "bg-gray-100 text-boz-neutral hover:bg-gray-200"
                  }`}
                >
                  {city}
                </button>
              ))}
            </div>
          </div>

          {calibration && (
            <CalibrationChart
              buckets={calibration.calibration_buckets}
              brierScore={calibration.brier_score}
            />
          )}

          {sources && <SourceAccuracyChart sources={sources} />}
        </div>

        {/* Accuracy Over Time */}
        {data.accuracy_over_time.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
            <h3 className="text-sm font-semibold mb-3">
              Daily Win Rate Over Time
            </h3>
            <div className="space-y-1">
              {data.accuracy_over_time.map((point) => (
                <div
                  key={point.date}
                  className="flex items-center gap-2 text-xs"
                >
                  <span className="text-boz-neutral w-20">{point.date}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
                    <div
                      className="h-full bg-boz-primary rounded-full"
                      style={{ width: `${point.accuracy * 100}%` }}
                    />
                  </div>
                  <span className="font-medium w-10 text-right">
                    {formatProbability(point.accuracy)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}
