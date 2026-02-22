"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SourceAccuracy } from "@/lib/types";

interface SourceAccuracyChartProps {
  sources: SourceAccuracy[];
}

/**
 * Source accuracy bar chart — compares MAE and RMSE across weather sources.
 * Grouped bars: blue for MAE, amber for RMSE.
 */
export default function SourceAccuracyChart({
  sources,
}: SourceAccuracyChartProps) {
  if (sources.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
        <h3 className="text-sm font-semibold mb-2">
          Forecast Source Accuracy
        </h3>
        <p className="text-xs text-boz-neutral">
          No source accuracy data available yet.
        </p>
      </div>
    );
  }

  const data = sources.map((s) => ({
    source: s.source,
    MAE: Number(s.mae_f.toFixed(1)),
    RMSE: Number(s.rmse_f.toFixed(1)),
    Bias: Number(s.bias_f.toFixed(1)),
    samples: s.sample_count,
  }));

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold mb-3">Forecast Source Accuracy</h3>

      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="source" tick={{ fontSize: 10 }} />
          <YAxis
            tick={{ fontSize: 10 }}
            label={{
              value: "Error (\u00b0F)",
              angle: -90,
              position: "insideLeft",
              fontSize: 10,
            }}
          />
          <Tooltip
            formatter={(value: number, name: string) => [
              `${value}\u00b0F`,
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="MAE" fill="#3b82f6" radius={[2, 2, 0, 0]} />
          <Bar dataKey="RMSE" fill="#f59e0b" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>

      {/* Bias annotations */}
      <div className="mt-2 flex flex-wrap gap-3">
        {data.map((d) => (
          <span key={d.source} className="text-[10px] text-boz-neutral">
            {d.source} bias:{" "}
            <span
              className={
                d.Bias > 0
                  ? "text-red-600"
                  : d.Bias < 0
                    ? "text-blue-600"
                    : "text-gray-600"
              }
            >
              {d.Bias > 0 ? "+" : ""}
              {d.Bias}&deg;F
            </span>{" "}
            ({d.samples} samples)
          </span>
        ))}
      </div>
    </div>
  );
}
