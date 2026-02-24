"use client";

import LogsViewer from "@/components/logs/logs-viewer";
import ErrorBoundary from "@/components/ui/error-boundary";
import WeatherTicker from "@/components/weather-ticker/weather-ticker";

export default function LogsPage() {
  return (
    <ErrorBoundary>
      <h1 className="text-xl font-bold mb-4">System Logs</h1>
      <WeatherTicker />
      <LogsViewer />
    </ErrorBoundary>
  );
}
