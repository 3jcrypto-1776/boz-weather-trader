import { fireEvent, render, screen } from "@testing-library/react";

import CalendarGrid from "@/components/calendar/calendar-grid";
import type { CalendarDay } from "@/lib/types";

const makeDays = (): CalendarDay[] => [
  {
    date: "2026-02-10",
    trade_count: 2,
    wins: 1,
    losses: 1,
    pnl_cents: 50,
    win_rate: 0.5,
  },
  {
    date: "2026-02-15",
    trade_count: 3,
    wins: 2,
    losses: 1,
    pnl_cents: -30,
    win_rate: 0.6667,
  },
];

describe("CalendarGrid", () => {
  it("renders 7 day-of-week headers", () => {
    render(
      <CalendarGrid
        year={2026}
        month={2}
        days={[]}
        onDayClick={vi.fn()}
        selectedDate={null}
      />
    );
    expect(screen.getByText("Sun")).toBeInTheDocument();
    expect(screen.getByText("Mon")).toBeInTheDocument();
    expect(screen.getByText("Tue")).toBeInTheDocument();
    expect(screen.getByText("Wed")).toBeInTheDocument();
    expect(screen.getByText("Thu")).toBeInTheDocument();
    expect(screen.getByText("Fri")).toBeInTheDocument();
    expect(screen.getByText("Sat")).toBeInTheDocument();
  });

  it("renders day numbers for the month", () => {
    render(
      <CalendarGrid
        year={2026}
        month={2}
        days={[]}
        onDayClick={vi.fn()}
        selectedDate={null}
      />
    );
    // February 2026 has 28 days
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("28")).toBeInTheDocument();
  });

  it("shows P&L on trading days", () => {
    render(
      <CalendarGrid
        year={2026}
        month={2}
        days={makeDays()}
        onDayClick={vi.fn()}
        selectedDate={null}
      />
    );
    // Feb 10 has +$0.50
    expect(screen.getByText("+$0.50")).toBeInTheDocument();
    // Feb 15 has -$0.30
    expect(screen.getByText("-$0.30")).toBeInTheDocument();
  });

  it("shows trade count badges on trading days", () => {
    const { container } = render(
      <CalendarGrid
        year={2026}
        month={2}
        days={makeDays()}
        onDayClick={vi.fn()}
        selectedDate={null}
      />
    );
    // Trade count badges have a specific class (rounded-full)
    const badges = container.querySelectorAll(".rounded-full");
    const badgeTexts = Array.from(badges).map((b) => b.textContent);
    expect(badgeTexts).toContain("2"); // Feb 10: 2 trades
    expect(badgeTexts).toContain("3"); // Feb 15: 3 trades
  });

  it("calls onDayClick when a trading day is clicked", () => {
    const handleClick = vi.fn();
    render(
      <CalendarGrid
        year={2026}
        month={2}
        days={makeDays()}
        onDayClick={handleClick}
        selectedDate={null}
      />
    );
    // Click on the cell that contains the P&L for Feb 10
    const pnlElement = screen.getByText("+$0.50");
    const cell = pnlElement.closest("button");
    if (cell) fireEvent.click(cell);
    expect(handleClick).toHaveBeenCalledWith("2026-02-10");
  });

  it("does not call onDayClick for empty days", () => {
    const handleClick = vi.fn();
    render(
      <CalendarGrid
        year={2026}
        month={2}
        days={makeDays()}
        onDayClick={handleClick}
        selectedDate={null}
      />
    );
    // Day 1 has no trades — click should be disabled
    const day1 = screen.getByText("1").closest("button");
    if (day1) fireEvent.click(day1);
    expect(handleClick).not.toHaveBeenCalled();
  });
});
