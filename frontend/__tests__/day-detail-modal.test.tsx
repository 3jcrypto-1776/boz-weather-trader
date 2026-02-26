import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CalendarDay, TradeRecord } from "@/lib/types";

// Mock hooks
const mockUseTrades = vi.fn();
vi.mock("@/lib/hooks", () => ({
  useTrades: (...args: unknown[]) => mockUseTrades(...args),
}));

// Mock next/navigation for BottomNav
vi.mock("next/navigation", () => ({
  usePathname: () => "/trades",
  useRouter: () => ({ push: vi.fn() }),
}));

import DayDetailModal from "@/components/calendar/day-detail-modal";

function makeTrade(overrides: Partial<TradeRecord> = {}): TradeRecord {
  return {
    id: "t1",
    kalshi_order_id: "order-1",
    city: "NYC",
    date: "2026-02-20",
    market_ticker: "KXHIGHNYC-26FEB20-T55",
    bracket_label: "55-56°F",
    side: "yes",
    price_cents: 25,
    quantity: 1,
    model_probability: 0.3,
    market_probability: 0.25,
    ev_at_entry: 0.05,
    confidence: "medium",
    status: "WON",
    settlement_temp_f: 55.5,
    settlement_source: "NWS",
    pnl_cents: 75,
    fees_cents: null,
    postmortem_narrative: null,
    created_at: "2026-02-20T10:00:00Z",
    settled_at: "2026-02-20T18:00:00Z",
    ...overrides,
  };
}

const DAY_STATS: CalendarDay = {
  date: "2026-02-20",
  trade_count: 3,
  wins: 2,
  losses: 1,
  pnl_cents: 150,
  win_rate: 0.67,
};

const MOCK_TRADES: TradeRecord[] = [
  makeTrade({ id: "t1", city: "NYC", pnl_cents: 75 }),
  makeTrade({
    id: "t2",
    city: "CHI",
    market_ticker: "KXHIGHCHI-26FEB20-T30",
    bracket_label: "30-31°F",
    pnl_cents: -25,
    status: "LOST",
  }),
  makeTrade({
    id: "t3",
    city: "MIA",
    market_ticker: "KXHIGHMIA-26FEB20-T80",
    bracket_label: "80-81°F",
    pnl_cents: 100,
  }),
];

describe("DayDetailModal", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockUseTrades.mockReturnValue({
      data: { trades: MOCK_TRADES, total: 3 },
      isLoading: false,
    });
  });

  it("renders date and P&L summary", () => {
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    expect(screen.getByText("3 trades")).toBeInTheDocument();
    expect(screen.getByText("2W / 1L")).toBeInTheDocument();
    expect(screen.getByText("+$1.50")).toBeInTheDocument();
    expect(screen.getByText("67% win rate")).toBeInTheDocument();
  });

  it("renders trades grouped by market", () => {
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    expect(screen.getByText("NYC")).toBeInTheDocument();
    expect(screen.getByText("55-56°F")).toBeInTheDocument();
    expect(screen.getByText("30-31°F")).toBeInTheDocument();
    expect(screen.getByText("80-81°F")).toBeInTheDocument();
  });

  it("shows loading skeletons", () => {
    mockUseTrades.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("shows empty state when no trades found", () => {
    mockUseTrades.mockReturnValue({
      data: { trades: [], total: 0 },
      isLoading: false,
    });
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    expect(screen.getByText("No trades found for this date.")).toBeInTheDocument();
  });

  it("closes on X button click", () => {
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    fireEvent.click(screen.getByTestId("modal-close-btn"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on backdrop click", () => {
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    fireEvent.click(screen.getByTestId("day-detail-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not close when clicking modal content", () => {
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    fireEvent.click(screen.getByTestId("day-detail-modal"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes on Escape key", () => {
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders sort buttons with Time active by default", () => {
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    const timeBtn = screen.getByTestId("sort-time");
    expect(timeBtn).toHaveClass("bg-boz-primary");
    expect(screen.getByTestId("sort-pnl")).not.toHaveClass("bg-boz-primary");
  });

  it("switches sort when clicking a sort button", () => {
    render(
      <DayDetailModal date="2026-02-20" dayStats={DAY_STATS} onClose={onClose} />,
    );
    fireEvent.click(screen.getByTestId("sort-city"));
    expect(screen.getByTestId("sort-city")).toHaveClass("bg-boz-primary");
    expect(screen.getByTestId("sort-time")).not.toHaveClass("bg-boz-primary");
  });
});
