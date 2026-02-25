import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UserSettings, VersionInfo } from "@/lib/types";

// Mock hooks
const mockUseSettings = vi.fn();
const mockUseAuthStatus = vi.fn();
const mockUseVersion = vi.fn();
vi.mock("@/lib/hooks", () => ({
  useSettings: () => mockUseSettings(),
  useAuthStatus: () => mockUseAuthStatus(),
  useCurrentWeather: () => ({ data: undefined, error: undefined }),
  useVersion: () => mockUseVersion(),
}));

// Mock API
vi.mock("@/lib/api", () => ({
  updateSettings: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock SWR mutate
vi.mock("swr", async () => {
  const actual = await vi.importActual("swr");
  return { ...actual, mutate: vi.fn() };
});

// Mock next/navigation
vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
}));

import SettingsPage from "@/app/settings/page";

const MOCK_SETTINGS: UserSettings = {
  trading_mode: "manual",
  max_trade_size_cents: 100,
  daily_loss_limit_cents: 1000,
  max_daily_exposure_cents: 2500,
  min_ev_threshold: 0.05,
  cooldown_per_loss_minutes: 60,
  consecutive_loss_limit: 3,
  active_cities: ["NYC", "CHI", "MIA", "AUS"],
  notifications_enabled: true,
  max_contracts_per_bracket: 3,
  enable_consecutive_loss_limit: true,
};

describe("Version Info on Settings Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    mockUseAuthStatus.mockReturnValue({
      data: {
        authenticated: true,
        user_id: "test-user",
        demo_mode: true,
        key_id_prefix: "abc123...",
      },
      error: undefined,
      isLoading: false,
    });
    mockUseSettings.mockReturnValue({
      data: MOCK_SETTINGS,
      error: undefined,
      isLoading: false,
    });
  });

  it("displays current version", () => {
    mockUseVersion.mockReturnValue({
      data: {
        current_version: "1.0.0",
        latest_version: "1.0.0",
        update_available: false,
        release_url: null,
      } as VersionInfo,
      error: undefined,
    });

    render(<SettingsPage />);
    expect(screen.getByTestId("current-version")).toHaveTextContent("v1.0.0");
  });

  it("shows up-to-date message when on latest version", () => {
    mockUseVersion.mockReturnValue({
      data: {
        current_version: "1.0.0",
        latest_version: "1.0.0",
        update_available: false,
        release_url: null,
      } as VersionInfo,
      error: undefined,
    });

    render(<SettingsPage />);
    expect(screen.getByTestId("up-to-date")).toHaveTextContent(
      "You're running the latest version"
    );
  });

  it("shows update banner when update is available", () => {
    mockUseVersion.mockReturnValue({
      data: {
        current_version: "1.0.0",
        latest_version: "1.1.0",
        update_available: true,
        release_url: "https://github.com/test/test/releases/tag/v1.1.0",
      } as VersionInfo,
      error: undefined,
    });

    render(<SettingsPage />);
    expect(screen.getByText("Update available")).toBeInTheDocument();
    expect(screen.getByText("v1.1.0 is now available")).toBeInTheDocument();
    expect(screen.getByTestId("update-link")).toHaveAttribute(
      "href",
      "https://github.com/test/test/releases/tag/v1.1.0"
    );
  });

  it("shows loading placeholder when version not loaded yet", () => {
    mockUseVersion.mockReturnValue({
      data: undefined,
      error: undefined,
    });

    render(<SettingsPage />);
    expect(screen.getByTestId("current-version")).toHaveTextContent("v...");
  });

  it("handles version fetch error gracefully", () => {
    mockUseVersion.mockReturnValue({
      data: undefined,
      error: new Error("Failed to fetch"),
    });

    render(<SettingsPage />);
    // Should still render the page without crashing
    expect(screen.getByText("About")).toBeInTheDocument();
    expect(screen.getByTestId("current-version")).toHaveTextContent("v...");
  });
});
