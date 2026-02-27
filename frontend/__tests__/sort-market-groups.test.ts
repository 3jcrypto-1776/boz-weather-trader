import { describe, expect, it } from "vitest";

import {
  sortMarketGroups,
  type DaySortOption,
} from "@/lib/trade-grouping";
import type { GroupedTrade, MarketGroup } from "@/lib/types";

/** Build a minimal MarketGroup for testing sort behavior. */
function makeMarket(overrides: {
  city: string;
  date: string;
  pnlCents?: number;
  status?: string;
}): MarketGroup {
  const group: GroupedTrade = {
    groupKey: `${overrides.city}-${overrides.date}|bracket|yes|${overrides.status ?? "WON"}`,
    city: overrides.city as GroupedTrade["city"],
    date: overrides.date,
    market_ticker: `KXHIGH${overrides.city}-${overrides.date}`,
    bracket_label: "55-56°F",
    side: "yes",
    status: (overrides.status ?? "WON") as GroupedTrade["status"],
    confidence: "medium",
    totalQuantity: 1,
    totalCostCents: 25,
    vwapCents: 25,
    totalPnlCents: overrides.pnlCents ?? 0,
    avgModelProbability: 0.3,
    avgMarketProbability: 0.25,
    avgEvAtEntry: 0.05,
    tradeIds: ["t1"],
    trades: [],
    earliestCreatedAt: `${overrides.date}T10:00:00Z`,
    latestCreatedAt: `${overrides.date}T10:00:00Z`,
    settlement_temp_f: null,
    settlement_source: null,
    postmortem_narrative: null,
  };

  return {
    label: `${overrides.city} High Temp`,
    marketKey: `${overrides.city}|${overrides.date}`,
    city: overrides.city as MarketGroup["city"],
    date: overrides.date,
    groups: [group],
  };
}

describe("sortMarketGroups", () => {
  const markets: MarketGroup[] = [
    makeMarket({ city: "MIA", date: "2026-02-20", pnlCents: -50, status: "LOST" }),
    makeMarket({ city: "NYC", date: "2026-02-22", pnlCents: 200, status: "WON" }),
    makeMarket({ city: "AUS", date: "2026-02-21", pnlCents: 75, status: "OPEN" }),
    makeMarket({ city: "CHI", date: "2026-02-23", pnlCents: 0, status: "CANCELED" }),
  ];

  it("sorts by time (date descending)", () => {
    const result = sortMarketGroups(markets, "time");
    expect(result.map((m) => m.city)).toEqual(["CHI", "NYC", "AUS", "MIA"]);
  });

  it("sorts by P&L (highest first)", () => {
    const result = sortMarketGroups(markets, "pnl");
    expect(result.map((m) => m.city)).toEqual(["NYC", "AUS", "CHI", "MIA"]);
  });

  it("sorts by city (alphabetical, then date descending)", () => {
    const result = sortMarketGroups(markets, "city");
    expect(result.map((m) => m.city)).toEqual(["AUS", "CHI", "MIA", "NYC"]);
  });

  it("sorts by status priority (RESTING → OPEN → WON → LOST → CANCELED)", () => {
    const result = sortMarketGroups(markets, "status");
    expect(result.map((m) => m.city)).toEqual(["AUS", "NYC", "MIA", "CHI"]);
  });

  it("sorts RESTING before OPEN in status sort", () => {
    const restingMarket = makeMarket({
      city: "NYC",
      date: "2026-02-24",
      status: "RESTING",
    });
    const withResting = [...markets, restingMarket];
    const result = sortMarketGroups(withResting, "status");
    // RESTING (rank 0) should come first, then OPEN, WON, LOST, CANCELED
    expect(result[0].groups[0].status).toBe("RESTING");
  });

  it("returns a new array without mutating input", () => {
    const original = [...markets];
    const result = sortMarketGroups(markets, "pnl");
    expect(result).not.toBe(markets);
    expect(markets.map((m) => m.city)).toEqual(original.map((m) => m.city));
  });
});
