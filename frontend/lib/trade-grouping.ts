/**
 * Frontend-only trade grouping utilities.
 *
 * Groups individual TradeRecord[] into aggregated GroupedTrade[] by
 * (market_ticker, bracket_label, side, status), then optionally partitions
 * into MarketGroup[] sections for display with section headers.
 */

import type {
  TradeRecord,
  GroupedTrade,
  MarketGroup,
  CityCode,
  ConfidenceLevel,
} from "./types";
import { CITY_NAMES, formatDate } from "./utils";

const CONFIDENCE_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };

/** Build a grouping key from a trade's identifying fields. */
function buildGroupKey(trade: TradeRecord): string {
  const marketId = trade.market_ticker ?? `${trade.city}-${trade.date}`;
  return `${marketId}|${trade.bracket_label}|${trade.side}|${trade.status}`;
}

/** Build a market key for section headers (city + date). */
function buildMarketKey(cityOrGroup: { city: CityCode; date: string }): string {
  return `${cityOrGroup.city}|${cityOrGroup.date}`;
}

/** Build a human-readable market label like "New York High Temp Fri, Feb 21". */
function buildMarketLabel(city: CityCode, date: string): string {
  const cityName = CITY_NAMES[city] ?? city;
  const formattedDate = formatDate(date);
  return `${cityName} High Temp ${formattedDate}`;
}

/**
 * Group trades by (market_ticker, bracket_label, side, status).
 *
 * Returns GroupedTrade[] sorted by earliest created_at descending (newest first).
 * Single-trade groups are still returned as GroupedTrade with that trade's values.
 */
export function groupTrades(trades: TradeRecord[]): GroupedTrade[] {
  if (trades.length === 0) return [];

  const map = new Map<string, TradeRecord[]>();

  for (const trade of trades) {
    const key = buildGroupKey(trade);
    const existing = map.get(key);
    if (existing) {
      existing.push(trade);
    } else {
      map.set(key, [trade]);
    }
  }

  const groups: GroupedTrade[] = [];

  map.forEach((groupTrades, key) => {
    const first = groupTrades[0];

    const totalQuantity = groupTrades.reduce((sum, t) => sum + t.quantity, 0);

    const totalCostCents = groupTrades.reduce(
      (sum, t) => sum + t.price_cents * t.quantity,
      0,
    );

    const vwapCents =
      totalQuantity > 0 ? Math.round(totalCostCents / totalQuantity) : 0;

    // P&L: null for OPEN trades, sum for settled
    let totalPnlCents: number | null = null;
    if (first.status !== "OPEN") {
      totalPnlCents = groupTrades.reduce(
        (sum, t) => sum + (t.pnl_cents ?? 0),
        0,
      );
    }

    // Weighted averages by quantity
    const avgModelProbability =
      totalQuantity > 0
        ? groupTrades.reduce(
            (sum, t) => sum + t.model_probability * t.quantity,
            0,
          ) / totalQuantity
        : 0;

    const avgMarketProbability =
      totalQuantity > 0
        ? groupTrades.reduce(
            (sum, t) => sum + t.market_probability * t.quantity,
            0,
          ) / totalQuantity
        : 0;

    const avgEvAtEntry =
      totalQuantity > 0
        ? groupTrades.reduce(
            (sum, t) => sum + t.ev_at_entry * t.quantity,
            0,
          ) / totalQuantity
        : 0;

    // Highest confidence in the group
    const confidence = groupTrades.reduce((best, t) => {
      return (CONFIDENCE_RANK[t.confidence] ?? 0) >
        (CONFIDENCE_RANK[best] ?? 0)
        ? t.confidence
        : best;
    }, first.confidence) as ConfidenceLevel;

    // Timestamps
    const createdAts = groupTrades.map((t) => t.created_at).sort();

    // Settlement info from any settled trade
    const settledTrade = groupTrades.find((t) => t.settlement_temp_f != null);

    // Post-mortem from any trade that has one
    const narrativeTrade = groupTrades.find(
      (t) => t.postmortem_narrative != null,
    );

    groups.push({
      groupKey: key,
      city: first.city,
      date: first.date,
      market_ticker: first.market_ticker,
      bracket_label: first.bracket_label,
      side: first.side,
      status: first.status,
      confidence,
      totalQuantity,
      totalCostCents,
      vwapCents,
      totalPnlCents,
      avgModelProbability,
      avgMarketProbability,
      avgEvAtEntry,
      tradeIds: groupTrades.map((t) => t.id),
      trades: groupTrades,
      earliestCreatedAt: createdAts[0],
      latestCreatedAt: createdAts[createdAts.length - 1],
      settlement_temp_f: settledTrade?.settlement_temp_f ?? null,
      settlement_source: settledTrade?.settlement_source ?? null,
      postmortem_narrative: narrativeTrade?.postmortem_narrative ?? null,
    });
  });

  // Newest groups first
  groups.sort((a, b) =>
    b.earliestCreatedAt.localeCompare(a.earliestCreatedAt),
  );

  return groups;
}

/**
 * Organize trades into market sections with human-readable headers.
 *
 * Returns MarketGroup[] sorted by date descending.
 */
export function groupByMarket(trades: TradeRecord[]): MarketGroup[] {
  const grouped = groupTrades(trades);

  const marketMap = new Map<
    string,
    { city: CityCode; date: string; groups: GroupedTrade[] }
  >();

  for (const group of grouped) {
    const mKey = buildMarketKey(group);
    const existing = marketMap.get(mKey);
    if (existing) {
      existing.groups.push(group);
    } else {
      marketMap.set(mKey, {
        city: group.city,
        date: group.date,
        groups: [group],
      });
    }
  }

  const markets: MarketGroup[] = [];
  marketMap.forEach(({ city, date, groups }, mKey) => {
    markets.push({
      label: buildMarketLabel(city, date),
      marketKey: mKey,
      city,
      date,
      groups,
    });
  });

  // Newest markets first
  markets.sort((a, b) => b.date.localeCompare(a.date));

  return markets;
}

// ─── Sorting ───

export type DaySortOption = "time" | "pnl" | "city" | "status";

const STATUS_RANK: Record<string, number> = {
  OPEN: 0,
  WON: 1,
  LOST: 2,
  CANCELED: 3,
};

/**
 * Sort MarketGroup[] by a chosen criterion. Returns a new array (no mutation).
 */
export function sortMarketGroups(
  markets: MarketGroup[],
  sortBy: DaySortOption,
): MarketGroup[] {
  const sorted = [...markets];

  switch (sortBy) {
    case "time":
      // Default: newest date first
      sorted.sort((a, b) => b.date.localeCompare(a.date));
      break;

    case "pnl":
      // Highest aggregate P&L first
      sorted.sort((a, b) => {
        const aPnl = a.groups.reduce(
          (s, g) => s + (g.totalPnlCents ?? 0),
          0,
        );
        const bPnl = b.groups.reduce(
          (s, g) => s + (g.totalPnlCents ?? 0),
          0,
        );
        return bPnl - aPnl;
      });
      break;

    case "city":
      // Alphabetical by city, then date descending
      sorted.sort(
        (a, b) =>
          a.city.localeCompare(b.city) || b.date.localeCompare(a.date),
      );
      break;

    case "status": {
      // Best (lowest rank) status in each market group
      const bestRank = (m: MarketGroup) =>
        Math.min(...m.groups.map((g) => STATUS_RANK[g.status] ?? 99));
      sorted.sort(
        (a, b) =>
          bestRank(a) - bestRank(b) || b.date.localeCompare(a.date),
      );
      break;
    }
  }

  return sorted;
}
