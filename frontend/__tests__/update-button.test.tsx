import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UpdateStatus, UserSettings, VersionInfo } from "@/lib/types";

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
const mockTriggerUpdate = vi.fn();
const mockFetchUpdateStatus = vi.fn();
vi.mock("@/lib/api", () => ({
  updateSettings: vi.fn(),
  disconnect: vi.fn(),
  triggerUpdate: (...args: unknown[]) => mockTriggerUpdate(...args),
  fetchUpdateStatus: (...args: unknown[]) => mockFetchUpdateStatus(...args),
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
  min_ev_threshold_yes: 0.15,
  min_ev_threshold_no: 0.05,
  cooldown_per_loss_minutes: 60,
  consecutive_loss_limit: 3,
  active_cities: ["NYC", "CHI", "MIA", "AUS"],
  notifications_enabled: true,
  max_contracts_per_bracket: 3,
  enable_consecutive_loss_limit: true,
  enable_per_loss_cooldown: true,
  model_weight: 0.4,
  max_model_market_divergence: 0.25,
  min_market_prob_for_yes: 0.15,
  fee_estimate_mode: "conservative",
  timezone: "",
};

describe("Update Button on Settings Page", () => {
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

  it("shows update button when update is available", () => {
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
    expect(screen.getByTestId("update-button")).toBeInTheDocument();
    expect(screen.getByTestId("update-button")).toHaveTextContent(
      "Update & Restart"
    );
  });

  it("does not show update button when up-to-date", () => {
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
    expect(screen.queryByTestId("update-button")).not.toBeInTheDocument();
  });

  it("shows confirmation dialog when update button is clicked", () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
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
    fireEvent.click(screen.getByTestId("update-button"));

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining("pull the latest code")
    );
  });

  it("shows progress during update", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockTriggerUpdate.mockResolvedValue({
      status: "started",
      message: "Update process initiated",
    });
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
    fireEvent.click(screen.getByTestId("update-button"));

    await waitFor(() => {
      expect(screen.getByTestId("update-progress")).toBeInTheDocument();
    });
  });

  it("shows error state with retry option", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mockTriggerUpdate.mockRejectedValue(new Error("Connection refused"));
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
    fireEvent.click(screen.getByTestId("update-button"));

    await waitFor(() => {
      expect(screen.getByTestId("update-error")).toBeInTheDocument();
      expect(screen.getByText("Retry")).toBeInTheDocument();
    });
  });
});
