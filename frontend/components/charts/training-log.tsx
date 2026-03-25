"use client";

import { useState } from "react";
import {
  Brain,
  ChevronDown,
  ChevronRight,
  Clock,
  RefreshCw,
  Timer,
} from "lucide-react";

import { triggerRetraining } from "@/lib/api";
import { useTimezone } from "@/lib/timezone-context";
import type { TrainingReport, TrainingReportList } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

interface TrainingLogProps {
  data: TrainingReportList;
  onMutate?: () => void;
}

/** Trigger badge color by trigger type. */
function triggerBadge(triggeredBy: string) {
  switch (triggeredBy) {
    case "schedule":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-700">
          <Clock className="w-3 h-3" />
          Scheduled
        </span>
      );
    case "settlement":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-100 text-purple-700">
          <Timer className="w-3 h-3" />
          Settlement
        </span>
      );
    case "manual":
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-700">
          <RefreshCw className="w-3 h-3" />
          Manual
        </span>
      );
    default:
      return (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600">
          {triggeredBy}
        </span>
      );
  }
}

/** Status badge color/label. */
function statusBadge(status: string) {
  switch (status) {
    case "completed":
      return (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-100 text-green-700">
          Completed
        </span>
      );
    case "skipped":
      return (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-yellow-100 text-yellow-700">
          Skipped
        </span>
      );
    case "error":
      return (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-100 text-red-700">
          Error
        </span>
      );
    default:
      return (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-600">
          {status}
        </span>
      );
  }
}

/** Format weights object into readable string. */
function formatWeights(
  weights: Record<string, number> | null
): string {
  if (!weights || Object.keys(weights).length === 0) return "—";
  return Object.entries(weights)
    .map(([k, v]) => `${k}: ${(v * 100).toFixed(1)}%`)
    .join(", ");
}

/** Single expandable report card. */
function ReportCard({ report }: { report: TrainingReport }) {
  const [expanded, setExpanded] = useState(false);
  const tz = useTimezone();

  const dateTimeStr = formatDateTime(report.completed_at, tz);

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Collapsed header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors"
        data-testid={`report-card-${report.id}`}
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-boz-neutral flex-shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-boz-neutral flex-shrink-0" />
        )}
        <span className="text-xs text-boz-neutral whitespace-nowrap">
          {dateTimeStr}
        </span>
        <div className="flex items-center gap-1.5 flex-wrap">
          {triggerBadge(report.triggered_by)}
          {statusBadge(report.status)}
        </div>
        <span className="text-xs text-boz-neutral ml-auto whitespace-nowrap">
          {report.training_samples > 0 && (
            <>{report.training_samples} samples &middot; </>
          )}
          {report.duration_seconds.toFixed(1)}s
        </span>
      </button>

      {/* Expanded details */}
      {expanded && (
        <div className="px-3 pb-3 space-y-3 border-t border-gray-100 bg-gray-50/50">
          {/* Trigger reason */}
          {report.trigger_reason && (
            <div className="pt-2">
              <span className="text-[10px] uppercase font-semibold text-boz-neutral">
                Trigger Reason
              </span>
              <p className="text-xs text-boz-text mt-0.5">
                {report.trigger_reason.replace(/_/g, " ")}
              </p>
            </div>
          )}

          {/* Model metrics table */}
          {report.model_metrics.length > 0 && (
            <div>
              <span className="text-[10px] uppercase font-semibold text-boz-neutral">
                Model Performance
              </span>
              <div className="mt-1 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-1 pr-3 font-medium">
                        Model
                      </th>
                      <th className="text-right py-1 px-2 font-medium">
                        RMSE
                      </th>
                      <th className="text-right py-1 px-2 font-medium">MAE</th>
                      <th className="text-center py-1 pl-2 font-medium">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.model_metrics.map((m) => (
                      <tr
                        key={m.model_name}
                        className="border-b border-gray-100"
                      >
                        <td className="py-1 pr-3 font-medium">
                          {m.model_name}
                        </td>
                        <td className="py-1 px-2 text-right">
                          {m.rmse?.toFixed(2) ?? "—"}
                        </td>
                        <td className="py-1 px-2 text-right">
                          {m.mae?.toFixed(2) ?? "—"}
                        </td>
                        <td className="py-1 pl-2 text-center">
                          {m.error ? (
                            <span className="text-boz-danger">{m.error}</span>
                          ) : m.accepted ? (
                            <span className="text-boz-success">Accepted</span>
                          ) : (
                            <span className="text-boz-danger">Rejected</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Weight changes */}
          {(report.weights_before || report.weights_after) && (
            <div>
              <span className="text-[10px] uppercase font-semibold text-boz-neutral">
                ML Model Weights
              </span>
              <div className="text-xs mt-0.5 space-y-0.5">
                <div>
                  <span className="text-boz-neutral">Before:</span>{" "}
                  {formatWeights(report.weights_before)}
                </div>
                <div>
                  <span className="text-boz-neutral">After:</span>{" "}
                  {formatWeights(report.weights_after)}
                </div>
              </div>
            </div>
          )}

          {/* Source weight changes */}
          {(report.source_weights_before || report.source_weights_after) && (
            <div>
              <span className="text-[10px] uppercase font-semibold text-boz-neutral">
                Source Ensemble Weights
              </span>
              <div className="text-xs mt-0.5 space-y-0.5">
                <div>
                  <span className="text-boz-neutral">Before:</span>{" "}
                  {formatWeights(report.source_weights_before)}
                </div>
                <div>
                  <span className="text-boz-neutral">After:</span>{" "}
                  {formatWeights(report.source_weights_after)}
                </div>
              </div>
            </div>
          )}

          {/* Brier score change */}
          {(report.brier_score_before !== null ||
            report.brier_score_after !== null) && (
            <div>
              <span className="text-[10px] uppercase font-semibold text-boz-neutral">
                Brier Score
              </span>
              <div className="flex items-center gap-2 mt-0.5 text-xs">
                <span>
                  {report.brier_score_before?.toFixed(3) ?? "—"}
                </span>
                <span className="text-boz-neutral">&rarr;</span>
                <span>
                  {report.brier_score_after?.toFixed(3) ?? "—"}
                </span>
                {report.brier_score_before !== null &&
                  report.brier_score_after !== null && (
                    <span
                      className={`font-medium ${
                        report.brier_score_after < report.brier_score_before
                          ? "text-boz-success"
                          : report.brier_score_after >
                              report.brier_score_before
                            ? "text-boz-danger"
                            : "text-boz-neutral"
                      }`}
                    >
                      (
                      {report.brier_score_after < report.brier_score_before
                        ? ""
                        : "+"}
                      {(
                        report.brier_score_after - report.brier_score_before
                      ).toFixed(3)}
                      )
                    </span>
                  )}
              </div>
            </div>
          )}

          {/* Data range */}
          {report.training_samples > 0 && (
            <div className="text-xs text-boz-neutral">
              {report.training_samples} training / {report.test_samples} test
              samples
              {report.date_range_start && report.date_range_end && (
                <>
                  {" "}
                  &middot; Data:{" "}
                  {new Date(report.date_range_start).toLocaleDateString("en-US", tz ? { timeZone: tz } : undefined)} –{" "}
                  {new Date(report.date_range_end).toLocaleDateString("en-US", tz ? { timeZone: tz } : undefined)}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Training Log — displays training report history with expandable cards.
 * Includes a "Retrain Now" button to manually trigger retraining.
 */
export default function TrainingLog({ data, onMutate }: TrainingLogProps) {
  const [isRetraining, setIsRetraining] = useState(false);

  const handleRetrain = async () => {
    setIsRetraining(true);
    try {
      await triggerRetraining();
      // Wait a beat for the task to dispatch, then refresh
      setTimeout(() => {
        onMutate?.();
        setIsRetraining(false);
      }, 2000);
    } catch {
      setIsRetraining(false);
    }
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold flex items-center gap-1.5">
          <Brain className="w-4 h-4 text-boz-primary" />
          Model Training Log
        </h3>
        <button
          onClick={handleRetrain}
          disabled={isRetraining}
          className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-boz-primary text-white hover:bg-boz-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          data-testid="retrain-button"
        >
          <RefreshCw
            className={`w-3 h-3 ${isRetraining ? "animate-spin" : ""}`}
          />
          {isRetraining ? "Retraining..." : "Retrain Now"}
        </button>
      </div>

      {data.reports.length === 0 ? (
        <p className="text-xs text-boz-neutral py-4 text-center">
          No training reports yet. Reports will appear after the first model
          training run.
        </p>
      ) : (
        <div className="space-y-2">
          {data.reports.map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
          {data.total > data.reports.length && (
            <p className="text-xs text-boz-neutral text-center pt-1">
              Showing {data.reports.length} of {data.total} reports
            </p>
          )}
        </div>
      )}
    </div>
  );
}
