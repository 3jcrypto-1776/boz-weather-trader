"use client";

import { X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import TradeCard from "@/components/trade-card/trade-card";
import Skeleton from "@/components/ui/skeleton";
import { useTrades } from "@/lib/hooks";
import {
  groupByMarket,
  sortMarketGroups,
  type DaySortOption,
} from "@/lib/trade-grouping";
import type { CalendarDay } from "@/lib/types";
import { formatDateLong, formatPnL, formatProbability } from "@/lib/utils";

interface DayDetailModalProps {
  date: string; // YYYY-MM-DD
  dayStats: CalendarDay;
  onClose: () => void;
}

const SORT_OPTIONS: { value: DaySortOption; label: string }[] = [
  { value: "time", label: "Time" },
  { value: "pnl", label: "P&L" },
  { value: "city", label: "City" },
  { value: "status", label: "Status" },
];

/**
 * Full-screen modal overlay showing trade cards for a selected calendar day.
 * Replaces the old inline DayDetailPanel with a centered popup.
 */
export default function DayDetailModal({
  date,
  dayStats,
  onClose,
}: DayDetailModalProps) {
  const [sortBy, setSortBy] = useState<DaySortOption>("time");
  const closeRef = useRef<HTMLButtonElement>(null);

  const { data, isLoading } = useTrades(1, undefined, undefined, date);

  const displayDate = formatDateLong(date);

  const marketGroups = useMemo(() => {
    if (!data) return [];
    return sortMarketGroups(groupByMarket(data.trades), sortBy);
  }, [data, sortBy]);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Lock body scroll while modal is open
  useEffect(() => {
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = original;
    };
  }, []);

  // Auto-focus close button on mount
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  // Backdrop click closes; stopPropagation on card prevents it
  const handleBackdropClick = useCallback(() => {
    onClose();
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={handleBackdropClick}
      data-testid="day-detail-backdrop"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" />

      {/* Modal card */}
      <div
        className="relative bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
        data-testid="day-detail-modal"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200">
          <div>
            <h3 className="text-sm font-bold">{displayDate}</h3>
            <div className="flex items-center gap-3 mt-1">
              <span
                className={`text-sm font-bold ${
                  dayStats.pnl_cents >= 0
                    ? "text-boz-success"
                    : "text-boz-danger"
                }`}
              >
                {formatPnL(dayStats.pnl_cents)}
              </span>
              <span className="text-xs text-boz-neutral">
                {dayStats.trade_count} trades
              </span>
              <span className="text-xs text-boz-neutral">
                {dayStats.wins}W / {dayStats.losses}L
              </span>
              <span className="text-xs text-boz-neutral">
                {formatProbability(dayStats.win_rate)} win rate
              </span>
            </div>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-boz-neutral"
            aria-label="Close day details"
            data-testid="modal-close-btn"
          >
            <X size={18} />
          </button>
        </div>

        {/* Sort bar */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-100">
          <span className="text-[10px] font-semibold text-boz-neutral uppercase tracking-wide">
            Sort
          </span>
          <div className="flex gap-1">
            {SORT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setSortBy(opt.value)}
                className={`min-h-[32px] px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                  sortBy === opt.value
                    ? "bg-boz-primary text-white"
                    : "bg-white border border-gray-200 text-boz-neutral hover:bg-gray-50"
                }`}
                data-testid={`sort-${opt.value}`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1 p-4">
          {isLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <Skeleton key={i} className="h-20" />
              ))}
            </div>
          ) : marketGroups.length === 0 ? (
            <p className="text-xs text-boz-neutral text-center py-4">
              No trades found for this date.
            </p>
          ) : (
            <div className="space-y-4">
              {marketGroups.map((market) => (
                <div key={market.marketKey}>
                  <h4 className="text-xs font-semibold text-boz-neutral mb-2">
                    {market.label}
                  </h4>
                  <div className="space-y-2">
                    {market.groups.map((group) => (
                      <TradeCard key={group.groupKey} group={group} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
