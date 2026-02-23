"use client";

import { X } from "lucide-react";

import TradeCard from "@/components/trade-card/trade-card";
import Skeleton from "@/components/ui/skeleton";
import { useTrades } from "@/lib/hooks";
import { groupByMarket, groupTrades } from "@/lib/trade-grouping";
import type { CalendarDay } from "@/lib/types";
import { formatDateLong, formatPnL, formatProbability } from "@/lib/utils";

interface DayDetailPanelProps {
  date: string; // YYYY-MM-DD
  dayStats: CalendarDay;
  onClose: () => void;
}

/**
 * Slide-out panel showing individual trade cards for a selected calendar day.
 * Fetches trades for the date and renders using existing TradeCard + groupByMarket.
 */
export default function DayDetailPanel({
  date,
  dayStats,
  onClose,
}: DayDetailPanelProps) {
  const { data, isLoading } = useTrades(
    1,
    undefined,
    undefined,
    date
  );

  // Format the display date using centralized formatter
  const displayDate = formatDateLong(date);

  const marketGroups = data
    ? groupByMarket(data.trades)
    : [];

  return (
    <div className="bg-white rounded-lg border border-gray-200 shadow-lg mt-4">
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
          onClick={onClose}
          className="p-1 rounded hover:bg-gray-100 text-boz-neutral"
          aria-label="Close day details"
        >
          <X size={18} />
        </button>
      </div>

      {/* Trade list */}
      <div className="p-4">
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
  );
}
