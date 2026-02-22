"use client";

import type { CalendarDay } from "@/lib/types";
import { formatPnL } from "@/lib/utils";

interface CalendarGridProps {
  year: number;
  month: number; // 1-indexed
  days: CalendarDay[];
  onDayClick: (date: string) => void;
  selectedDate: string | null;
}

const DAY_HEADERS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Build the 6x7 calendar grid for a given year/month.
 * Returns an array of 42 cells, each either a day number or null (padding).
 */
function buildCalendarCells(year: number, month: number): (number | null)[] {
  const firstDay = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const startDow = firstDay.getDay(); // 0=Sun

  const cells: (number | null)[] = [];

  // Padding before first day
  for (let i = 0; i < startDow; i++) cells.push(null);

  // Days of the month
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  // Padding after last day (fill to 42 = 6 rows)
  while (cells.length < 42) cells.push(null);

  return cells;
}

function formatDate(year: number, month: number, day: number): string {
  const m = String(month).padStart(2, "0");
  const d = String(day).padStart(2, "0");
  return `${year}-${m}-${d}`;
}

export default function CalendarGrid({
  year,
  month,
  days,
  onDayClick,
  selectedDate,
}: CalendarGridProps) {
  const cells = buildCalendarCells(year, month);

  // Index days by date string for O(1) lookup
  const dayMap = new Map<string, CalendarDay>();
  for (const d of days) {
    dayMap.set(d.date, d);
  }

  return (
    <div>
      {/* Day-of-week headers */}
      <div className="grid grid-cols-7 gap-px mb-px">
        {DAY_HEADERS.map((h) => (
          <div
            key={h}
            className="text-center text-[10px] font-semibold text-boz-neutral py-1 bg-gray-50"
          >
            {h}
          </div>
        ))}
      </div>

      {/* Calendar cells */}
      <div className="grid grid-cols-7 gap-px bg-gray-200">
        {cells.map((dayNum, idx) => {
          if (dayNum === null) {
            return (
              <div
                key={`pad-${idx}`}
                className="bg-gray-50 min-h-[60px] lg:min-h-[80px]"
              />
            );
          }

          const dateStr = formatDate(year, month, dayNum);
          const dayData = dayMap.get(dateStr);
          const isSelected = selectedDate === dateStr;
          const hasTrades = dayData && dayData.trade_count > 0;

          // Background color based on P&L
          let bgClass = "bg-white";
          if (hasTrades) {
            bgClass =
              dayData.pnl_cents > 0
                ? "bg-green-50"
                : dayData.pnl_cents < 0
                  ? "bg-red-50"
                  : "bg-white";
          }

          return (
            <button
              key={dateStr}
              onClick={() => hasTrades && onDayClick(dateStr)}
              disabled={!hasTrades}
              className={`
                ${bgClass} min-h-[60px] lg:min-h-[80px] p-1 text-left
                transition-all relative
                ${hasTrades ? "cursor-pointer hover:ring-2 hover:ring-blue-400" : "cursor-default"}
                ${isSelected ? "ring-2 ring-blue-500 z-10" : ""}
              `}
            >
              {/* Day number + trade count badge */}
              <div className="flex items-start justify-between">
                <span
                  className={`text-xs font-medium ${
                    hasTrades ? "text-gray-900" : "text-gray-400"
                  }`}
                >
                  {dayNum}
                </span>
                {hasTrades && (
                  <span className="text-[9px] bg-gray-200 text-gray-700 rounded-full px-1.5 leading-4">
                    {dayData.trade_count}
                  </span>
                )}
              </div>

              {/* P&L + win rate */}
              {hasTrades && (
                <div className="mt-1">
                  <div
                    className={`text-xs lg:text-sm font-bold ${
                      dayData.pnl_cents >= 0
                        ? "text-green-700"
                        : "text-red-700"
                    }`}
                  >
                    {formatPnL(dayData.pnl_cents)}
                  </div>
                  <div className="hidden lg:block text-[9px] text-boz-neutral mt-0.5">
                    {dayData.wins}W/{dayData.losses}L &middot;{" "}
                    {Math.round(dayData.win_rate * 100)}%
                  </div>
                </div>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
