import { fireEvent, render, screen } from "@testing-library/react";

import TrainingLog from "@/components/charts/training-log";
import type { TrainingReport, TrainingReportList } from "@/lib/types";

// Mock the api module
vi.mock("@/lib/api", () => ({
  triggerRetraining: vi.fn(),
}));

// Mock lucide-react icons
vi.mock("lucide-react", () => ({
  Brain: () => <span data-testid="brain-icon" />,
  ChevronDown: () => <span data-testid="chevron-down" />,
  ChevronRight: () => <span data-testid="chevron-right" />,
  Clock: () => <span data-testid="clock-icon" />,
  RefreshCw: () => <span data-testid="refresh-icon" />,
  Timer: () => <span data-testid="timer-icon" />,
}));

const makeReport = (overrides?: Partial<TrainingReport>): TrainingReport => ({
  id: 1,
  triggered_by: "schedule",
  trigger_reason: "weekly",
  status: "completed",
  training_samples: 200,
  test_samples: 50,
  date_range_start: "2026-01-01T00:00:00",
  date_range_end: "2026-02-20T00:00:00",
  model_metrics: [
    { model_name: "xgboost", rmse: 2.1, mae: 1.5, accepted: true, error: null },
    { model_name: "ridge", rmse: 2.8, mae: 2.0, accepted: true, error: null },
  ],
  weights_before: { xgboost: 0.5, ridge: 0.5 },
  weights_after: { xgboost: 0.55, ridge: 0.45 },
  source_weights_before: { NWS: 0.4, ECMWF: 0.6 },
  source_weights_after: { NWS: 0.45, ECMWF: 0.55 },
  brier_score_before: 0.18,
  brier_score_after: 0.16,
  duration_seconds: 12.5,
  completed_at: "2026-02-24T03:00:00",
  ...overrides,
});

const makeData = (reports: TrainingReport[] = []): TrainingReportList => ({
  reports,
  total: reports.length,
});

describe("TrainingLog", () => {
  it("renders empty state when no reports", () => {
    render(<TrainingLog data={makeData()} />);
    expect(screen.getByText(/no training reports yet/i)).toBeInTheDocument();
  });

  it("renders the header with retrain button", () => {
    render(<TrainingLog data={makeData()} />);
    expect(screen.getByText("Model Training Log")).toBeInTheDocument();
    expect(screen.getByTestId("retrain-button")).toBeInTheDocument();
    expect(screen.getByText("Retrain Now")).toBeInTheDocument();
  });

  it("renders report cards", () => {
    const reports = [makeReport({ id: 1 }), makeReport({ id: 2 })];
    render(<TrainingLog data={makeData(reports)} />);
    expect(screen.getByTestId("report-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("report-card-2")).toBeInTheDocument();
  });

  it("shows trigger badges", () => {
    const reports = [
      makeReport({ id: 1, triggered_by: "schedule" }),
      makeReport({ id: 2, triggered_by: "settlement" }),
      makeReport({ id: 3, triggered_by: "manual" }),
    ];
    render(<TrainingLog data={makeData(reports)} />);
    expect(screen.getByText("Scheduled")).toBeInTheDocument();
    expect(screen.getByText("Settlement")).toBeInTheDocument();
    expect(screen.getByText("Manual")).toBeInTheDocument();
  });

  it("shows status badges", () => {
    const reports = [
      makeReport({ id: 1, status: "completed" }),
      makeReport({ id: 2, status: "skipped" }),
      makeReport({ id: 3, status: "error" }),
    ];
    render(<TrainingLog data={makeData(reports)} />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByText("Error")).toBeInTheDocument();
  });

  it("expands report card on click", () => {
    const report = makeReport({ trigger_reason: "weekly" });
    render(<TrainingLog data={makeData([report])} />);

    // Model metrics should not be visible initially
    expect(screen.queryByText("xgboost")).not.toBeInTheDocument();

    // Click to expand
    fireEvent.click(screen.getByTestId("report-card-1"));

    // Now model metrics should be visible
    expect(screen.getByText("xgboost")).toBeInTheDocument();
    expect(screen.getByText("ridge")).toBeInTheDocument();
    // Both models are accepted
    expect(screen.getAllByText("Accepted")).toHaveLength(2);
  });

  it("shows model metrics table when expanded", () => {
    const report = makeReport({
      model_metrics: [
        { model_name: "xgboost", rmse: 2.0, mae: 1.4, accepted: true, error: null },
        {
          model_name: "ridge",
          rmse: 3.0,
          mae: 2.2,
          accepted: false,
          error: "RMSE too high",
        },
      ],
    });
    render(<TrainingLog data={makeData([report])} />);

    fireEvent.click(screen.getByTestId("report-card-1"));

    expect(screen.getByText("2.00")).toBeInTheDocument(); // RMSE for xgboost
    // Ridge has error set → shows error message (not "Rejected")
    expect(screen.getByText("RMSE too high")).toBeInTheDocument();
    expect(screen.getByText("Accepted")).toBeInTheDocument(); // xgboost
  });

  it("shows weight comparison when expanded", () => {
    const report = makeReport();
    render(<TrainingLog data={makeData([report])} />);

    fireEvent.click(screen.getByTestId("report-card-1"));

    expect(screen.getByText("ML Model Weights")).toBeInTheDocument();
    expect(screen.getByText("Source Ensemble Weights")).toBeInTheDocument();
  });

  it("shows Brier score delta when expanded", () => {
    const report = makeReport({
      brier_score_before: 0.2,
      brier_score_after: 0.15,
    });
    render(<TrainingLog data={makeData([report])} />);

    fireEvent.click(screen.getByTestId("report-card-1"));

    expect(screen.getByText("Brier Score")).toBeInTheDocument();
    expect(screen.getByText("0.200")).toBeInTheDocument();
    expect(screen.getByText("0.150")).toBeInTheDocument();
  });

  it("calls triggerRetraining when retrain button clicked", async () => {
    const { triggerRetraining } = await import("@/lib/api");
    (triggerRetraining as ReturnType<typeof vi.fn>).mockResolvedValue({
      status: "dispatched",
      message: "ok",
    });

    const onMutate = vi.fn();
    render(<TrainingLog data={makeData()} onMutate={onMutate} />);

    fireEvent.click(screen.getByTestId("retrain-button"));

    expect(triggerRetraining).toHaveBeenCalled();
  });

  it("shows total count when more reports exist", () => {
    const reports = [makeReport({ id: 1 })];
    const data: TrainingReportList = { reports, total: 25 };
    render(<TrainingLog data={data} />);

    expect(screen.getByText("Showing 1 of 25 reports")).toBeInTheDocument();
  });
});
