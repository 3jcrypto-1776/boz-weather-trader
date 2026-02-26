"use client";

import { Brain, BarChart3, Clock } from "lucide-react";
import type { TrainingReport } from "@/lib/types";

/** Friendly display names for weather sources. */
function sourceLabel(key: string): string {
  const map: Record<string, string> = {
    NWS: "NWS",
    "NWS:gridpoint": "NWS Gridpoint",
    "Open-Meteo:ICON": "ICON",
    "Open-Meteo:ECMWF": "ECMWF",
    "Open-Meteo:GFS": "GFS",
    "Open-Meteo:GEM": "GEM",
  };
  return map[key] ?? key;
}

/** Color for the weight bar based on relative weight. */
function weightBarColor(weight: number): string {
  if (weight >= 0.22) return "bg-boz-success";
  if (weight >= 0.18) return "bg-boz-primary";
  return "bg-boz-neutral";
}

interface Props {
  report: TrainingReport;
}

export default function ModelStatus({ report }: Props) {
  const trainedAt = new Date(report.completed_at);
  const formattedDate = trainedAt.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const formattedTime = trainedAt.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });

  // Sort source weights descending
  const sourceWeights = report.source_weights_after ?? report.source_weights_before;
  const sortedSources = sourceWeights
    ? Object.entries(sourceWeights).sort(([, a], [, b]) => b - a)
    : [];

  // Find the max weight for scaling bars
  const maxWeight = sortedSources.length > 0 ? sortedSources[0][1] : 1;

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-boz-primary" />
          <h3 className="text-sm font-semibold">Current Model Status</h3>
        </div>
        <div className="flex items-center gap-1 text-[11px] text-boz-neutral">
          <Clock className="w-3 h-3" />
          <span>
            Last trained {formattedDate} {formattedTime}
          </span>
          <span className="mx-1">·</span>
          <span>
            {report.training_samples} train / {report.test_samples} test samples
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Model Performance Table */}
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <Brain className="w-3.5 h-3.5 text-boz-neutral" />
            <span className="text-xs font-medium text-boz-neutral">
              ML Model Performance
            </span>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-boz-neutral border-b border-gray-100">
                <th className="text-left py-1.5 font-medium">Model</th>
                <th className="text-right py-1.5 font-medium">RMSE</th>
                <th className="text-right py-1.5 font-medium">MAE</th>
                <th className="text-right py-1.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {report.model_metrics.map((m) => (
                <tr
                  key={m.model_name}
                  className="border-b border-gray-50 last:border-0"
                >
                  <td className="py-1.5 font-medium">{m.model_name}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    {m.rmse != null ? `${m.rmse.toFixed(2)}\u00B0F` : "\u2014"}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">
                    {m.mae != null ? `${m.mae.toFixed(2)}\u00B0F` : "\u2014"}
                  </td>
                  <td className="py-1.5 text-right">
                    {m.accepted ? (
                      <span className="text-boz-success font-medium">
                        Accepted
                      </span>
                    ) : (
                      <span className="text-boz-danger font-medium">
                        {m.error ?? "Failed"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Ensemble Weights */}
          {report.weights_after && (
            <div className="mt-2 pt-2 border-t border-gray-100">
              <span className="text-[11px] text-boz-neutral">
                Ensemble blend:{" "}
                {Object.entries(report.weights_after)
                  .map(
                    ([name, w]) =>
                      `${name} ${(w * 100).toFixed(1)}%`
                  )
                  .join(", ")}
              </span>
            </div>
          )}
        </div>

        {/* Source Weights Table */}
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <BarChart3 className="w-3.5 h-3.5 text-boz-neutral" />
            <span className="text-xs font-medium text-boz-neutral">
              Source Ensemble Weights
            </span>
          </div>
          {sortedSources.length > 0 ? (
            <div className="space-y-1.5">
              {sortedSources.map(([source, weight]) => (
                <div key={source} className="flex items-center gap-2">
                  <span className="text-xs w-24 truncate" title={source}>
                    {sourceLabel(source)}
                  </span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2.5 overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${weightBarColor(weight)}`}
                      style={{
                        width: `${(weight / maxWeight) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs font-medium tabular-nums w-12 text-right">
                    {(weight * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-boz-neutral">
              No source weights computed yet.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
