import { describe, expect, it } from "vitest";

import {
  centsToDollars,
  confidenceBadgeColor,
  formatDate,
  formatDateTime,
  formatPnL,
  formatProbability,
  formatTime,
  parsePostmortemSections,
  shortBracketLabel,
  statusColor,
  timeRemaining,
  CITY_NAMES,
} from "@/lib/utils";

describe("centsToDollars", () => {
  it("converts positive cents", () => {
    expect(centsToDollars(150)).toBe("1.50");
  });

  it("converts zero", () => {
    expect(centsToDollars(0)).toBe("0.00");
  });

  it("converts negative cents", () => {
    expect(centsToDollars(-250)).toBe("-2.50");
  });

  it("handles small amounts", () => {
    expect(centsToDollars(1)).toBe("0.01");
  });

  it("handles large amounts", () => {
    expect(centsToDollars(100000)).toBe("1000.00");
  });
});

describe("formatPnL", () => {
  it("formats positive P&L with plus sign", () => {
    expect(formatPnL(500)).toBe("+$5.00");
  });

  it("formats negative P&L with minus sign", () => {
    expect(formatPnL(-250)).toBe("-$2.50");
  });

  it("formats zero as positive", () => {
    expect(formatPnL(0)).toBe("+$0.00");
  });

  it("formats single cent", () => {
    expect(formatPnL(1)).toBe("+$0.01");
  });
});

describe("formatProbability", () => {
  it("formats decimal to percentage", () => {
    expect(formatProbability(0.3)).toBe("30%");
  });

  it("formats 1.0", () => {
    expect(formatProbability(1.0)).toBe("100%");
  });

  it("formats 0.0", () => {
    expect(formatProbability(0)).toBe("0%");
  });

  it("rounds to nearest integer", () => {
    expect(formatProbability(0.155)).toBe("16%");
  });
});

describe("formatDate", () => {
  it("formats ISO date string", () => {
    const result = formatDate("2025-02-18");
    // Output depends on locale, just verify it's a non-empty string
    expect(result).toBeTruthy();
    expect(typeof result).toBe("string");
  });

  it("formats Date object", () => {
    const result = formatDate(new Date(2025, 1, 18)); // Feb 18, 2025
    expect(result).toBeTruthy();
  });
});

describe("statusColor", () => {
  it("returns success color for WON", () => {
    expect(statusColor("WON")).toBe("text-boz-success");
  });

  it("returns danger color for LOST", () => {
    expect(statusColor("LOST")).toBe("text-boz-danger");
  });

  it("returns primary color for OPEN", () => {
    expect(statusColor("OPEN")).toBe("text-boz-primary");
  });

  it("returns neutral for CANCELED", () => {
    expect(statusColor("CANCELED")).toBe("text-boz-neutral");
  });

  it("returns default for unknown", () => {
    expect(statusColor("UNKNOWN")).toBe("text-gray-700");
  });
});

describe("confidenceBadgeColor", () => {
  it("returns green for high", () => {
    expect(confidenceBadgeColor("high")).toContain("green");
  });

  it("returns yellow for medium", () => {
    expect(confidenceBadgeColor("medium")).toContain("yellow");
  });

  it("returns red for low", () => {
    expect(confidenceBadgeColor("low")).toContain("red");
  });
});

describe("timeRemaining", () => {
  it("returns Expired for past dates", () => {
    const past = new Date(Date.now() - 60000).toISOString();
    expect(timeRemaining(past)).toBe("Expired");
  });

  it("returns minutes for near future", () => {
    const future = new Date(Date.now() + 30 * 60000).toISOString();
    const result = timeRemaining(future);
    expect(result).toMatch(/^\d+m$/);
  });

  it("returns hours and minutes for far future", () => {
    const future = new Date(Date.now() + 2 * 3600000 + 15 * 60000).toISOString();
    const result = timeRemaining(future);
    expect(result).toMatch(/^\d+h \d+m$/);
  });
});

describe("CITY_NAMES", () => {
  it("has all four cities", () => {
    expect(CITY_NAMES.NYC).toBe("New York");
    expect(CITY_NAMES.CHI).toBe("Chicago");
    expect(CITY_NAMES.MIA).toBe("Miami");
    expect(CITY_NAMES.AUS).toBe("Austin");
  });
});

describe("parsePostmortemSections", () => {
  it("parses multi-section narrative into header/content pairs", () => {
    const narrative = [
      "WHAT WE TRADED",
      "  Bought YES on 53-54F bracket",
      "",
      "WHAT HAPPENED",
      "  Actual high: 54F",
    ].join("\n");

    const sections = parsePostmortemSections(narrative);
    expect(sections).toHaveLength(2);
    expect(sections[0].header).toBe("WHAT WE TRADED");
    expect(sections[0].content).toContain("Bought YES");
    expect(sections[1].header).toBe("WHAT HAPPENED");
    expect(sections[1].content).toContain("Actual high");
  });

  it("handles old-format single-line narrative", () => {
    const narrative = "Simple one-line post-mortem.";
    const sections = parsePostmortemSections(narrative);
    expect(sections).toHaveLength(1);
    expect(sections[0].header).toBeNull();
    expect(sections[0].content).toBe("Simple one-line post-mortem.");
  });

  it("captures preamble before first header", () => {
    const narrative = [
      "TRADE #abcd -- NYC | Feb 18",
      "Result: WIN",
      "",
      "WHAT WE TRADED",
      "  Bought YES on bracket",
    ].join("\n");

    const sections = parsePostmortemSections(narrative);
    expect(sections.length).toBeGreaterThanOrEqual(2);
    // First section is the preamble (header line parsed as section header)
    // or content before first section
    const headers = sections.map((s) => s.header).filter(Boolean);
    expect(headers).toContain("WHAT WE TRADED");
  });

  it("returns empty content for empty narrative", () => {
    const sections = parsePostmortemSections("");
    expect(sections).toHaveLength(1);
    expect(sections[0].header).toBeNull();
    expect(sections[0].content).toBe("");
  });
});

describe("shortBracketLabel", () => {
  it("formats bottom edge bracket (null lower bound)", () => {
    expect(shortBracketLabel("52°F or below", null, 52)).toBe("≤52°");
  });

  it("formats top edge bracket (null upper bound)", () => {
    expect(shortBracketLabel("58°F or above", 58, null)).toBe("≥58°");
  });

  it("formats middle bracket with integer bounds", () => {
    expect(shortBracketLabel("52° to 53°F", 52, 53)).toBe("52-53°");
  });

  it("floors fractional bounds", () => {
    expect(shortBracketLabel("52° to 53°F", 52.0, 53.99)).toBe("52-53°");
  });

  it("falls back to bracket_label when both bounds null", () => {
    expect(shortBracketLabel("Unknown", null, null)).toBe("Unknown");
  });
});

// ─── Timezone-aware formatting ───

describe("formatDateTime with timezone", () => {
  it("formats in specified timezone", () => {
    // Midnight UTC = 7pm ET previous day
    const result = formatDateTime("2026-03-25T00:00:00Z", "America/New_York");
    expect(result).toContain("Mar 24");
    expect(result).toContain("8:00 PM");
  });

  it("formats without timezone param (browser default)", () => {
    const result = formatDateTime("2026-03-25T12:00:00Z");
    // Should not throw and should contain some date info
    expect(result).toContain("Mar");
  });
});

describe("formatTime with timezone", () => {
  it("formats time in specified timezone", () => {
    // 18:00 UTC = 12:00 PM CT (CDT in March)
    const result = formatTime("2026-03-25T18:00:00Z", "America/Chicago");
    expect(result).toContain("1:00 PM");
  });
});

describe("formatDate with timezone", () => {
  it("works with date-only string regardless of timezone", () => {
    // Date-only strings use noon-parsing trick so tz shouldn't change the date
    const resultET = formatDate("2026-03-25", "America/New_York");
    const resultPT = formatDate("2026-03-25", "America/Los_Angeles");
    expect(resultET).toContain("Mar 25");
    expect(resultPT).toContain("Mar 25");
  });
});
