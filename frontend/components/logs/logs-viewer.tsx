"use client";

import { FileText } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import EmptyState from "@/components/ui/empty-state";
import Skeleton from "@/components/ui/skeleton";
import { useLogs } from "@/lib/hooks";
import { formatDateTime } from "@/lib/utils";

const MODULE_OPTIONS = ["ALL", "WEATHER", "PREDICTION", "TRADING", "SYSTEM", "API"];
const LEVEL_OPTIONS = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"];

function levelColor(level: string): string {
  switch (level.toUpperCase()) {
    case "ERROR":
      return "text-boz-danger bg-red-50";
    case "WARNING":
      return "text-boz-warning bg-yellow-50";
    case "INFO":
      return "text-boz-primary bg-blue-50";
    case "DEBUG":
      return "text-boz-neutral bg-gray-50";
    default:
      return "text-gray-700 bg-gray-50";
  }
}

export default function LogsViewer() {
  const [moduleFilter, setModuleFilter] = useState("ALL");
  const [levelFilter, setLevelFilter] = useState("ALL");

  const params = {
    module: moduleFilter === "ALL" ? undefined : moduleFilter,
    level: levelFilter === "ALL" ? undefined : levelFilter,
  };
  const { data, error, isLoading } = useLogs(params);

  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [data, autoScroll]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    // If user scrolls up more than 100px from bottom, disable auto-scroll
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 100);
  };

  return (
    <>
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 mb-4">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold text-boz-neutral uppercase tracking-wide">
            Module
          </span>
          <div className="flex gap-1">
            {MODULE_OPTIONS.map((m) => (
              <button
                key={m}
                onClick={() => setModuleFilter(m)}
                className={`min-h-[36px] px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  moduleFilter === m
                    ? "bg-boz-primary text-white"
                    : "bg-white border border-gray-200 text-boz-neutral hover:bg-gray-50"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
        <div className="h-6 w-px bg-gray-200 hidden sm:block" />
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold text-boz-neutral uppercase tracking-wide">
            Level
          </span>
          <div className="flex gap-1">
            {LEVEL_OPTIONS.map((l) => (
              <button
                key={l}
                onClick={() => setLevelFilter(l)}
                className={`min-h-[36px] px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  levelFilter === l
                    ? "bg-boz-primary text-white"
                    : "bg-white border border-gray-200 text-boz-neutral hover:bg-gray-50"
                }`}
              >
                {l}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Auto-scroll indicator */}
      {!autoScroll && (
        <button
          onClick={() => setAutoScroll(true)}
          className="w-full text-xs text-boz-primary bg-blue-50 rounded-lg py-1 mb-2 hover:bg-blue-100 transition-colors"
        >
          ↓ Auto-scroll paused — click to resume
        </button>
      )}

      {/* Content */}
      {isLoading && (
        <div className="space-y-1">
          {[...Array(10)].map((_, i) => (
            <Skeleton key={i} className="h-8" />
          ))}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-boz-danger">
          {error.message || "Unable to load logs"}
        </div>
      )}

      {data && data.length === 0 && (
        <EmptyState
          icon={FileText}
          title="No Logs"
          description="System logs will appear here as the trading bot runs."
        />
      )}

      {data && data.length > 0 && (
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="bg-gray-900 rounded-lg p-3 max-h-[600px] overflow-y-auto"
        >
          <div className="space-y-0.5 font-mono text-xs">
            {data.map((entry) => (
              <div key={entry.id} className="flex gap-3 leading-relaxed">
                <span className="text-gray-500 whitespace-nowrap flex-shrink-0">
                  {formatDateTime(entry.timestamp)}
                </span>
                <span
                  className={`px-1.5 rounded text-[10px] font-bold uppercase flex-shrink-0 ${levelColor(entry.level)}`}
                >
                  {entry.level}
                </span>
                <span className="text-blue-400 flex-shrink-0">
                  [{entry.module}]
                </span>
                <span className="text-gray-200 break-all">
                  {entry.message}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
