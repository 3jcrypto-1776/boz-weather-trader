import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardData, DashboardStats } from "@/lib/types";

// Mock hooks
const mockUseDashboard = vi.fn();
const mockUseDashboardStats = vi.fn();
vi.mock("@/lib/hooks", () => ({
  useDashboard: () => mockUseDashboard(),
  useDashboardStats: () => mockUseDashboardStats(),
  useCurrentWeather: () => ({ data: undefined, error: undefined }),
}));

// Mock next/navigation for BottomNav + useRouter
const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: mockPush }),
}));

import DashboardPage from "@/app/page";

const MOCK_STATS: DashboardStats = {
  yesterday: { pnl_cents: 100, wins: 1, losses: 0 },
  week: { pnl_cents: 350, wins: 3, losses: 1 },
  month: { pnl_cents: 1200, wins: 10, losses: 5 },
  year: { pnl_cents: 5000, wins: 40, losses: 20 },
  all_time: { pnl_cents: 8000, wins: 60, losses: 30 },
};

const MOCK_DASHBOARD: DashboardData = {
  balance_cents: 50000,
  today_pnl_cents: 350,
  active_positions: [],
  recent_trades: [
    {
      id: "t1",
      kalshi_order_id: "order-1",
      city: "NYC",
      date: "2025-02-18",
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
      created_at: "2025-02-18T10:00:00Z",
      settled_at: "2025-02-18T18:00:00Z",
    },
  ],
  next_market_launch: "2025-02-19T06:00:00-05:00",
  predictions: [
    {
      city: "NYC",
      date: "2025-02-18",
      brackets: [
        {
          bracket_label: "≤52°F",
          lower_bound_f: null,
          upper_bound_f: 52,
          probability: 0.08,
        },
        {
          bracket_label: "53-54°F",
          lower_bound_f: 53,
          upper_bound_f: 54,
          probability: 0.15,
        },
        {
          bracket_label: "55-56°F",
          lower_bound_f: 55,
          upper_bound_f: 56,
          probability: 0.3,
        },
        {
          bracket_label: "57-58°F",
          lower_bound_f: 57,
          upper_bound_f: 58,
          probability: 0.28,
        },
        {
          bracket_label: "59-60°F",
          lower_bound_f: 59,
          upper_bound_f: 60,
          probability: 0.12,
        },
        {
          bracket_label: "≥61°F",
          lower_bound_f: 61,
          upper_bound_f: null,
          probability: 0.07,
        },
      ],
      ensemble_mean_f: 56.3,
      ensemble_std_f: 2.1,
      confidence: "medium",
      model_sources: ["NWS", "GFS", "ECMWF", "ICON"],
      generated_at: "2025-02-18T06:00:00Z",
    },
  ],
};

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseDashboardStats.mockReturnValue({ data: undefined, error: undefined });
  });

  it("shows loading skeletons", () => {
    mockUseDashboard.mockReturnValue({
      data: undefined,
      error: undefined,
      isLoading: true,
    });

    render(<DashboardPage />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    // Check for skeleton elements (aria-hidden divs with animate-pulse)
    const skeletons = document.querySelectorAll('[aria-hidden="true"]');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("shows error state", () => {
    mockUseDashboard.mockReturnValue({
      data: undefined,
      error: new Error("Server down"),
      isLoading: false,
    });

    render(<DashboardPage />);
    expect(screen.getByText("Server down")).toBeInTheDocument();
  });

  it("renders dashboard data with weekly P/L default", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });
    mockUseDashboardStats.mockReturnValue({ data: MOCK_STATS, error: undefined });

    render(<DashboardPage />);

    // Balance
    expect(screen.getByText("$500.00")).toBeInTheDocument();
    // Weekly P&L (default period)
    expect(screen.getByText("Weekly P&L")).toBeInTheDocument();
    expect(screen.getByText("+$3.50")).toBeInTheDocument();
    // Predictions section
    expect(screen.getByText("Predictions")).toBeInTheDocument();
    expect(screen.getAllByText("New York").length).toBeGreaterThanOrEqual(1);
  });

  it("renders prediction horizontal bars with bracket labels", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);

    // Abbreviated bracket labels should be visible
    expect(screen.getByText("≤52°")).toBeInTheDocument();
    expect(screen.getByText("55-56°")).toBeInTheDocument();
    expect(screen.getByText("≥61°")).toBeInTheDocument();

    // Peak bracket summary (55-56° at 30%)
    expect(screen.getByText(/55-56° \(30%\)/)).toBeInTheDocument();

    // Confidence shown in footer
    expect(screen.getByText("medium confidence")).toBeInTheDocument();
  });

  it("renders W/L record with all-time default", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });
    mockUseDashboardStats.mockReturnValue({ data: MOCK_STATS, error: undefined });

    render(<DashboardPage />);

    // All-time W/L (default)
    expect(screen.getByText("All-Time W/L")).toBeInTheDocument();
    expect(screen.getByText("60W / 30L")).toBeInTheDocument();
  });

  it("cycles P/L period on click", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });
    mockUseDashboardStats.mockReturnValue({ data: MOCK_STATS, error: undefined });

    render(<DashboardPage />);

    // Default: Weekly P&L (+$3.50)
    expect(screen.getByText("Weekly P&L")).toBeInTheDocument();

    // Click to cycle: week → yesterday
    const pnlCard = screen.getByText("Weekly P&L").closest("button");
    expect(pnlCard).toBeInTheDocument();
    fireEvent.click(pnlCard!);
    expect(screen.getByText("Yesterday P&L")).toBeInTheDocument();
    expect(screen.getByText("+$1.00")).toBeInTheDocument();

    // Click again: yesterday → month
    fireEvent.click(pnlCard!);
    expect(screen.getByText("Monthly P&L")).toBeInTheDocument();
    expect(screen.getByText("+$12.00")).toBeInTheDocument();
  });

  it("cycles W/L period on click", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });
    mockUseDashboardStats.mockReturnValue({ data: MOCK_STATS, error: undefined });

    render(<DashboardPage />);

    // Default: All-Time W/L
    expect(screen.getByText("All-Time W/L")).toBeInTheDocument();
    expect(screen.getByText("60W / 30L")).toBeInTheDocument();

    // Click to cycle: all_time → yesterday
    const wlCard = screen.getByText("All-Time W/L").closest("button");
    expect(wlCard).toBeInTheDocument();
    fireEvent.click(wlCard!);
    expect(screen.getByText("Yesterday W/L")).toBeInTheDocument();
    expect(screen.getByText("1W / 0L")).toBeInTheDocument();

    // Click again: yesterday → week
    fireEvent.click(wlCard!);
    expect(screen.getByText("Weekly W/L")).toBeInTheDocument();
    expect(screen.getByText("3W / 1L")).toBeInTheDocument();
  });

  it("falls back to today_pnl_cents when stats not loaded", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });
    // No stats loaded
    mockUseDashboardStats.mockReturnValue({ data: undefined, error: undefined });

    render(<DashboardPage />);
    // Falls back to today_pnl_cents from dashboard data
    expect(screen.getByText("+$3.50")).toBeInTheDocument();
    // W/L shows dash when no stats
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders recent trades", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);
    expect(screen.getByText("Recent Trades")).toBeInTheDocument();
    expect(screen.getByText("55-56°F")).toBeInTheDocument();
    expect(screen.getByText("WON")).toBeInTheDocument();
  });

  it("navigates to trades when Open Positions is clicked", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);
    const openPositionsCard = screen.getByText("Open Positions").closest("button");
    expect(openPositionsCard).toBeInTheDocument();
    fireEvent.click(openPositionsCard!);
    expect(mockPush).toHaveBeenCalledWith("/trades");
  });

  it("renders market section headers for recent trades", () => {
    mockUseDashboard.mockReturnValue({
      data: MOCK_DASHBOARD,
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);
    // groupByMarket creates "New York High Temp Tue, Feb 18" header
    expect(screen.getByText(/New York High Temp/)).toBeInTheDocument();
  });

  it("handles empty dashboard", () => {
    const emptyDashboard: DashboardData = {
      balance_cents: 10000,
      today_pnl_cents: 0,
      active_positions: [],
      recent_trades: [],
      next_market_launch: null,
      predictions: [],
    };

    mockUseDashboard.mockReturnValue({
      data: emptyDashboard,
      error: undefined,
      isLoading: false,
    });

    render(<DashboardPage />);
    expect(screen.getByText("$100.00")).toBeInTheDocument();
    expect(screen.getByText("+$0.00")).toBeInTheDocument();
  });
});
