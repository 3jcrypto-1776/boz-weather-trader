import { render, screen } from "@testing-library/react";

import ModelStatus from "@/components/model-status";
import type { TrainingReport } from "@/lib/types";

// Mock lucide-react icons
vi.mock("lucide-react", () => ({
  Brain: () => <span data-testid="brain-icon" />,
  BarChart3: () => <span data-testid="barchart-icon" />,
  Clock: () => <span data-testid="clock-icon" />,
}));

vi.mock("@/lib/timezone-context", () => ({
  useTimezone: () => undefined,
}));

const makeReport = (overrides?: Partial<TrainingReport>): TrainingReport => ({
  id: 1,
  triggered_by: "schedule",
  trigger_reason: "weekly",
  status: "completed",
  training_samples: 16,
  test_samples: 4,
  date_range_start: "2026-02-20",
  date_range_end: "2026-02-24",
  model_metrics: [
    { model_name: "XGBoost", rmse: 1.69, mae: 1.26, accepted: true, error: null },
    { model_name: "RandomForest", rmse: 2.10, mae: 1.80, accepted: true, error: null },
    { model_name: "Ridge", rmse: null, mae: null, accepted: false, error: "training_failed" },
  ],
  weights_before: { XGBoost: 0.555, RandomForest: 0.445 },
  weights_after: { XGBoost: 0.555, RandomForest: 0.445 },
  source_weights_before: null,
  source_weights_after: {
    NWS: 0.227,
    "NWS:gridpoint": 0.197,
    "Open-Meteo:ICON": 0.224,
    "Open-Meteo:GFS": 0.179,
    "Open-Meteo:ECMWF": 0.173,
  },
  brier_score_before: null,
  brier_score_after: 0.119,
  duration_seconds: 0.5,
  completed_at: "2026-02-25T22:31:00Z",
  ...overrides,
});

describe("ModelStatus", () => {
  it("renders the header with last trained date", () => {
    render(<ModelStatus report={makeReport()} />);
    expect(screen.getByText("Current Model Status")).toBeInTheDocument();
    expect(screen.getByText(/Last trained/)).toBeInTheDocument();
    expect(screen.getByText(/16 train \/ 4 test samples/)).toBeInTheDocument();
  });

  it("renders model performance table with all models", () => {
    render(<ModelStatus report={makeReport()} />);
    expect(screen.getByText("XGBoost")).toBeInTheDocument();
    expect(screen.getByText("RandomForest")).toBeInTheDocument();
    expect(screen.getByText("Ridge")).toBeInTheDocument();
  });

  it("shows RMSE and MAE for accepted models", () => {
    render(<ModelStatus report={makeReport()} />);
    expect(screen.getByText("1.69\u00B0F")).toBeInTheDocument();
    expect(screen.getByText("1.26\u00B0F")).toBeInTheDocument();
    expect(screen.getByText("2.10\u00B0F")).toBeInTheDocument();
    expect(screen.getByText("1.80\u00B0F")).toBeInTheDocument();
  });

  it("shows Accepted for passing models and error for failed ones", () => {
    render(<ModelStatus report={makeReport()} />);
    const accepted = screen.getAllByText("Accepted");
    expect(accepted).toHaveLength(2);
    expect(screen.getByText("training_failed")).toBeInTheDocument();
  });

  it("renders source weights sorted descending", () => {
    render(<ModelStatus report={makeReport()} />);
    expect(screen.getByText("NWS")).toBeInTheDocument();
    expect(screen.getByText("ICON")).toBeInTheDocument();
    expect(screen.getByText("ECMWF")).toBeInTheDocument();
    expect(screen.getByText("GFS")).toBeInTheDocument();
    expect(screen.getByText("NWS Gridpoint")).toBeInTheDocument();

    // Check percentages are displayed
    expect(screen.getByText("22.7%")).toBeInTheDocument();
    expect(screen.getByText("22.4%")).toBeInTheDocument();
    expect(screen.getByText("17.3%")).toBeInTheDocument();
  });

  it("renders ensemble blend weights", () => {
    render(<ModelStatus report={makeReport()} />);
    expect(screen.getByText(/Ensemble blend:/)).toBeInTheDocument();
    expect(screen.getByText(/XGBoost 55.5%/)).toBeInTheDocument();
  });

  it("handles null source weights gracefully", () => {
    render(
      <ModelStatus
        report={makeReport({
          source_weights_after: null,
          source_weights_before: null,
        })}
      />
    );
    expect(
      screen.getByText("No source weights computed yet.")
    ).toBeInTheDocument();
  });

  it("uses source_weights_before as fallback", () => {
    render(
      <ModelStatus
        report={makeReport({
          source_weights_after: null,
          source_weights_before: { NWS: 0.40, "Open-Meteo:ECMWF": 0.60 },
        })}
      />
    );
    expect(screen.getByText("40.0%")).toBeInTheDocument();
    expect(screen.getByText("60.0%")).toBeInTheDocument();
  });

  it("handles null weights_after gracefully", () => {
    render(
      <ModelStatus
        report={makeReport({ weights_after: null })}
      />
    );
    expect(screen.queryByText(/Ensemble blend:/)).not.toBeInTheDocument();
  });
});
