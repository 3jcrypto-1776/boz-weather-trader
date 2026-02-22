import { render, screen } from "@testing-library/react";

import SourceAccuracyChart from "@/components/charts/source-accuracy-chart";
import type { SourceAccuracy } from "@/lib/types";

// Mock recharts
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  BarChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="bar-chart">{children}</div>
  ),
  CartesianGrid: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  Tooltip: () => <div />,
  Legend: () => <div />,
  Bar: () => <div />,
}));

const makeSources = (): SourceAccuracy[] => [
  { source: "NWS", sample_count: 100, mae_f: 2.1, rmse_f: 2.8, bias_f: 0.5 },
  {
    source: "Open-Meteo",
    sample_count: 90,
    mae_f: 2.5,
    rmse_f: 3.1,
    bias_f: -0.3,
  },
];

describe("SourceAccuracyChart", () => {
  it("renders empty state when no sources", () => {
    render(<SourceAccuracyChart sources={[]} />);
    expect(
      screen.getByText("No source accuracy data available yet.")
    ).toBeInTheDocument();
  });

  it("renders chart with data", () => {
    render(<SourceAccuracyChart sources={makeSources()} />);
    expect(screen.getByTestId("bar-chart")).toBeInTheDocument();
  });

  it("shows bias annotations for each source", () => {
    render(<SourceAccuracyChart sources={makeSources()} />);
    expect(screen.getByText(/NWS bias:/)).toBeInTheDocument();
    expect(screen.getByText(/Open-Meteo bias:/)).toBeInTheDocument();
  });
});
