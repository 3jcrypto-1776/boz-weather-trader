"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CalibrationBucket } from "@/lib/types";

interface CalibrationChartProps {
  buckets: CalibrationBucket[];
  brierScore: number | null;
}

/**
 * Calibration chart — plots predicted probability vs actual outcome rate.
 * Perfect calibration is the 45-degree line (predicted = actual).
 * Brier score badge displayed above the chart.
 */
export default function CalibrationChart({
  buckets,
  brierScore,
}: CalibrationChartProps) {
  if (buckets.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
        <h3 className="text-sm font-semibold mb-2">Model Calibration</h3>
        <p className="text-xs text-boz-neutral">
          Not enough data for calibration analysis.
        </p>
      </div>
    );
  }

  // Format bucket data for the scatter chart
  const data = buckets.map((b) => ({
    predicted: Math.round(b.predicted_avg * 100),
    actual: Math.round(b.actual_rate * 100),
    samples: b.sample_count,
  }));

  // Perfect calibration line (0,0) to (100,100)
  const perfectLine = [
    { predicted: 0, actual: 0 },
    { predicted: 100, actual: 100 },
  ];

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold">Model Calibration</h3>
        {brierScore !== null && (
          <span
            className={`text-xs font-medium px-2 py-0.5 rounded-full ${
              brierScore <= 0.15
                ? "bg-green-100 text-green-800"
                : brierScore <= 0.25
                  ? "bg-yellow-100 text-yellow-800"
                  : "bg-red-100 text-red-800"
            }`}
          >
            Brier: {brierScore.toFixed(3)}
          </span>
        )}
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="predicted"
            domain={[0, 100]}
            name="Predicted"
            unit="%"
            tick={{ fontSize: 10 }}
            label={{
              value: "Predicted %",
              position: "insideBottom",
              offset: -10,
              fontSize: 10,
            }}
          />
          <YAxis
            type="number"
            dataKey="actual"
            domain={[0, 100]}
            name="Actual"
            unit="%"
            tick={{ fontSize: 10 }}
            label={{
              value: "Actual %",
              angle: -90,
              position: "insideLeft",
              fontSize: 10,
            }}
          />
          <Tooltip
            formatter={(value: number, name: string) => [
              `${value}%`,
              name === "predicted" ? "Predicted" : "Actual",
            ]}
          />
          <ReferenceLine
            segment={[
              { x: 0, y: 0 },
              { x: 100, y: 100 },
            ]}
            stroke="#d1d5db"
            strokeDasharray="5 5"
            label={{ value: "Perfect", fontSize: 9, fill: "#9ca3af" }}
          />
          <Scatter
            data={data}
            fill="#3b82f6"
            r={6}
            name="Calibration"
          />
        </ScatterChart>
      </ResponsiveContainer>

      <p className="text-[10px] text-boz-neutral mt-1 text-center">
        Points on the dashed line = perfectly calibrated predictions
      </p>
    </div>
  );
}
