import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TradeRecord } from "@/lib/types";

// Mock hooks
const mockUseTrades = vi.fn();
const mockUseCalendar = vi.fn();
const mockUseCurrentWeather = vi.fn();
const mockUseDashboardStats = vi.fn();
vi.mock("@/lib/hooks", () => ({
  useTrades: (...args: unknown[]) => mockUseTrades(...args),
  useCalendar: () => mockUseCalendar(),
  useCurrentWeather: () => mockUseCurrentWeather(),
  useDashboardStats: () => mockUseDashboardStats(),
}));

vi.mock("@/lib/api", () => ({
  syncTrades: vi.fn(),
}));

// Mock next/navigation for BottomNav
vi.mock("next/navigation", () => ({
  usePathname: () => "/trades",
  useRouter: () => ({ push: vi.fn() }),
}));

import TradesPage from "@/app/trades/page";

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
    status: "OPEN",
    settlement_temp_f: null,
    settlement_source: null,
    pnl_cents: null,
    fees_cents: null,
    postmortem_narrative: null,
    created_at: "2026-02-20T10:00:00Z",
    settled_at: null,
    ...overrides,
  };
}

const OPEN_TRADES: TradeRecord[] = [
  makeTrade({ id: "t1", city: "NYC" }),
  makeTrade({
    id: "t2",
    city: "CHI",
    market_ticker: "KXHIGHCHI-26FEB20-T30",
    bracket_label: "30-31°F",
  }),
  makeTrade({
    id: "t3",
    city: "MIA",
    market_ticker: "KXHIGHMIA-26FEB20-T80",
    bracket_label: "80-81°F",
  }),
];

describe("OpenPositionsSection — city toggles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: calendar loading, no stats, weather with temps
    mockUseCalendar.mockReturnValue({
      data: { year: 2026, month: 2, days: [], weeks: [], total_pnl_cents: 0, total_trades: 0, total_wins: 0, total_losses: 0, trading_days: 0 },
      isLoading: false,
      error: undefined,
    });
    mockUseDashboardStats.mockReturnValue({ data: undefined });
    mockUseCurrentWeather.mockReturnValue({
      data: {
        cities: [
          { city: "NYC", current_temp_f: 68.2 },
          { city: "CHI", current_temp_f: 45.5 },
          { city: "MIA", current_temp_f: 82.1 },
          { city: "AUS", current_temp_f: 71.0 },
        ],
      },
    });
    // Open trades for the OpenPositionsSection
    mockUseTrades.mockReturnValue({
      data: { trades: OPEN_TRADES, total: 3 },
      isLoading: false,
    });
  });

  it("renders toggle buttons for all 4 cities", () => {
    render(<TradesPage />);
    expect(screen.getByTestId("toggle-NYC")).toBeInTheDocument();
    expect(screen.getByTestId("toggle-CHI")).toBeInTheDocument();
    expect(screen.getByTestId("toggle-MIA")).toBeInTheDocument();
    expect(screen.getByTestId("toggle-AUS")).toBeInTheDocument();
  });

  it("all cities are active by default", () => {
    render(<TradesPage />);
    expect(screen.getByTestId("toggle-NYC")).toHaveClass("bg-boz-primary");
    expect(screen.getByTestId("toggle-CHI")).toHaveClass("bg-boz-primary");
    expect(screen.getByTestId("toggle-MIA")).toHaveClass("bg-boz-primary");
    expect(screen.getByTestId("toggle-AUS")).toHaveClass("bg-boz-primary");
  });

  it("toggling a city off hides its market trades", () => {
    render(<TradesPage />);
    // NYC bracket should be visible
    expect(screen.getByText("55-56°F")).toBeInTheDocument();

    // Toggle NYC off
    fireEvent.click(screen.getByTestId("toggle-NYC"));
    expect(screen.getByTestId("toggle-NYC")).not.toHaveClass("bg-boz-primary");
    expect(screen.queryByText("55-56°F")).not.toBeInTheDocument();
  });

  it("toggling a city back on shows its trades", () => {
    render(<TradesPage />);
    // Toggle off then on
    fireEvent.click(screen.getByTestId("toggle-NYC"));
    expect(screen.queryByText("55-56°F")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("toggle-NYC"));
    expect(screen.getByText("55-56°F")).toBeInTheDocument();
  });

  it("cannot deselect all cities — last one stays active", () => {
    render(<TradesPage />);
    // Deselect all except NYC, then try to deselect NYC
    fireEvent.click(screen.getByTestId("toggle-CHI"));
    fireEvent.click(screen.getByTestId("toggle-MIA"));
    fireEvent.click(screen.getByTestId("toggle-AUS"));

    // Only NYC active — clicking it should NOT deselect
    fireEvent.click(screen.getByTestId("toggle-NYC"));
    expect(screen.getByTestId("toggle-NYC")).toHaveClass("bg-boz-primary");
  });

  it("shows filtered count when some cities toggled off", () => {
    render(<TradesPage />);
    // Toggle off CHI — should show 2/3
    fireEvent.click(screen.getByTestId("toggle-CHI"));
    expect(screen.getByText("2/3")).toBeInTheDocument();
  });
});
