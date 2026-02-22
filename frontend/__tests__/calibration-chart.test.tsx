import { render, screen } from "@testing-library/react";

import CalibrationChart from "@/components/charts/calibration-chart";
import type { CalibrationBucket } from "@/lib/types";

// Mock recharts to avoid SVG rendering issues in tests
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  ScatterChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="scatter-chart">{children}</div>
  ),
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  Tooltip: () => <div data-testid="tooltip" />,
  ReferenceLine: () => <div data-testid="reference-line" />,
  Scatter: () => <div data-testid="scatter" />,
  Line: () => <div />,
  LineChart: () => <div />,
}));

const makeBuckets = (): CalibrationBucket[] => [
  {
    bin_start: 0.0,
    bin_end: 0.2,
    predicted_avg: 0.1,
    actual_rate: 0.08,
    sample_count: 50,
  },
  {
    bin_start: 0.2,
    bin_end: 0.4,
    predicted_avg: 0.3,
    actual_rate: 0.35,
    sample_count: 30,
  },
  {
    bin_start: 0.4,
    bin_end: 0.6,
    predicted_avg: 0.5,
    actual_rate: 0.48,
    sample_count: 20,
  },
];

describe("CalibrationChart", () => {
  it("renders empty state when no buckets", () => {
    render(<CalibrationChart buckets={[]} brierScore={null} />);
    expect(
      screen.getByText("Not enough data for calibration analysis.")
    ).toBeInTheDocument();
  });

  it("renders chart with data", () => {
    render(<CalibrationChart buckets={makeBuckets()} brierScore={0.12} />);
    expect(screen.getByTestId("scatter-chart")).toBeInTheDocument();
    expect(screen.getByTestId("reference-line")).toBeInTheDocument();
  });

  it("shows Brier score badge", () => {
    render(<CalibrationChart buckets={makeBuckets()} brierScore={0.12} />);
    expect(screen.getByText("Brier: 0.120")).toBeInTheDocument();
  });

  it("hides Brier badge when null", () => {
    render(<CalibrationChart buckets={makeBuckets()} brierScore={null} />);
    expect(screen.queryByText(/Brier:/)).not.toBeInTheDocument();
  });
});
