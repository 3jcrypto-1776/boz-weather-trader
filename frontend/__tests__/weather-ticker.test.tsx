import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CurrentWeatherResponse } from "@/lib/types";

// Mock hooks
const mockUseCurrentWeather = vi.fn();
vi.mock("@/lib/hooks", () => ({
  useCurrentWeather: () => mockUseCurrentWeather(),
}));

import WeatherTicker from "@/components/weather-ticker/weather-ticker";

const MOCK_WEATHER: CurrentWeatherResponse = {
  cities: [
    {
      city: "NYC",
      city_name: "New York",
      current_temp_f: 52.3,
      today_high_f: 58.1,
      today_low_f: 39.7,
    },
    {
      city: "CHI",
      city_name: "Chicago",
      current_temp_f: 35.0,
      today_high_f: 40.2,
      today_low_f: 28.5,
    },
    {
      city: "MIA",
      city_name: "Miami",
      current_temp_f: 78.6,
      today_high_f: 82.0,
      today_low_f: 68.1,
    },
    {
      city: "AUS",
      city_name: "Austin",
      current_temp_f: 65.4,
      today_high_f: 72.0,
      today_low_f: 50.3,
    },
  ],
  fetched_at: "2026-02-23T17:05:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("WeatherTicker", () => {
  it("renders all 4 cities with temps", () => {
    mockUseCurrentWeather.mockReturnValue({
      data: MOCK_WEATHER,
      error: undefined,
    });

    render(<WeatherTicker />);

    // All city codes should appear
    expect(screen.getByText("NYC")).toBeInTheDocument();
    expect(screen.getByText("CHI")).toBeInTheDocument();
    expect(screen.getByText("MIA")).toBeInTheDocument();
    expect(screen.getByText("AUS")).toBeInTheDocument();

    // Current temps (rounded)
    expect(screen.getByText("52°F")).toBeInTheDocument();
    expect(screen.getByText("35°F")).toBeInTheDocument();
    expect(screen.getByText("79°F")).toBeInTheDocument();
    expect(screen.getByText("65°F")).toBeInTheDocument();
  });

  it("shows high and low temps for each city", () => {
    mockUseCurrentWeather.mockReturnValue({
      data: MOCK_WEATHER,
      error: undefined,
    });

    render(<WeatherTicker />);

    // High temps (red-colored, separate spans)
    expect(screen.getByTestId("high-NYC")).toHaveTextContent("H:58");
    expect(screen.getByTestId("high-CHI")).toHaveTextContent("H:40");
    expect(screen.getByTestId("high-MIA")).toHaveTextContent("H:82");
    expect(screen.getByTestId("high-AUS")).toHaveTextContent("H:72");

    // Low temps (blue-colored, separate spans)
    expect(screen.getByTestId("low-NYC")).toHaveTextContent("L:40");
    expect(screen.getByTestId("low-CHI")).toHaveTextContent("L:29");
    expect(screen.getByTestId("low-MIA")).toHaveTextContent("L:68");
    expect(screen.getByTestId("low-AUS")).toHaveTextContent("L:50");
  });

  it("renders nothing when data is still loading", () => {
    mockUseCurrentWeather.mockReturnValue({
      data: undefined,
      error: undefined,
    });

    const { container } = render(<WeatherTicker />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when there is an error", () => {
    mockUseCurrentWeather.mockReturnValue({
      data: undefined,
      error: new Error("Network error"),
    });

    const { container } = render(<WeatherTicker />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when cities list is empty", () => {
    mockUseCurrentWeather.mockReturnValue({
      data: { cities: [], fetched_at: "2026-02-23T17:05:00Z" },
      error: undefined,
    });

    const { container } = render(<WeatherTicker />);
    expect(container.firstChild).toBeNull();
  });

  it("has the data-testid attribute for integration testing", () => {
    mockUseCurrentWeather.mockReturnValue({
      data: MOCK_WEATHER,
      error: undefined,
    });

    render(<WeatherTicker />);
    expect(screen.getByTestId("weather-ticker")).toBeInTheDocument();
  });
});
