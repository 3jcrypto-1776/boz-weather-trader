import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TradeCard from "@/components/trade-card/trade-card";
import type { GroupedTrade } from "@/lib/types";

function makeGroup(overrides: Partial<GroupedTrade> = {}): GroupedTrade {
  return {
    groupKey: "NYC-2026-02-20|55-56°F|yes|RESTING",
    city: "NYC",
    date: "2026-02-20",
    market_ticker: "KXHIGHNYC-26FEB20-T55",
    bracket_label: "55-56°F",
    side: "yes",
    status: "RESTING",
    confidence: "medium",
    totalQuantity: 1,
    totalCostCents: 22,
    vwapCents: 22,
    totalPnlCents: null,
    avgModelProbability: 0.3,
    avgMarketProbability: 0.22,
    avgEvAtEntry: 0.05,
    tradeIds: ["t1"],
    trades: [
      {
        id: "t1",
        kalshi_order_id: "order-1",
        city: "NYC",
        date: "2026-02-20",
        market_ticker: "KXHIGHNYC-26FEB20-T55",
        bracket_label: "55-56°F",
        side: "yes",
        price_cents: 22,
        quantity: 1,
        model_probability: 0.3,
        market_probability: 0.22,
        ev_at_entry: 0.05,
        confidence: "medium",
        status: "RESTING",
        settlement_temp_f: null,
        settlement_source: null,
        pnl_cents: null,
        fees_cents: null,
        postmortem_narrative: null,
        created_at: "2026-02-20T10:00:00Z",
        settled_at: null,
      },
    ],
    earliestCreatedAt: "2026-02-20T10:00:00Z",
    latestCreatedAt: "2026-02-20T10:00:00Z",
    settlement_temp_f: null,
    settlement_source: null,
    postmortem_narrative: null,
    ...overrides,
  };
}

describe("TradeCard — RESTING status", () => {
  it("renders RESTING status text", () => {
    render(<TradeCard group={makeGroup()} />);
    expect(screen.getByText("RESTING")).toBeInTheDocument();
  });

  it("has amber/warning border for RESTING status", () => {
    const { container } = render(<TradeCard group={makeGroup()} />);
    const card = container.querySelector(".border-l-4");
    expect(card).toHaveClass("border-l-boz-warning");
  });

  it("does not show P&L for RESTING trades", () => {
    render(<TradeCard group={makeGroup()} />);
    // RESTING trades have null P&L, no dollar amount should appear
    expect(screen.queryByText(/\+\$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/-\$/)).not.toBeInTheDocument();
  });

  it("shows current temp when provided", () => {
    render(<TradeCard group={makeGroup()} currentTempF={68.2} />);
    expect(screen.getByTestId("current-temp")).toHaveTextContent("Now: 68°F");
  });
});
