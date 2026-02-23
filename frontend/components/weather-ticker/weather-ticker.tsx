"use client";

import { Cloud } from "lucide-react";

import { useCurrentWeather } from "@/lib/hooks";
import type { CityCurrentWeather } from "@/lib/types";

/** Single city weather block inside the ticker. */
function CityWeather({ city }: { city: CityCurrentWeather }) {
  return (
    <div className="flex items-center gap-2 whitespace-nowrap">
      <span className="text-xs font-bold text-white">{city.city}</span>
      <span className="text-xs font-semibold text-amber-300" data-testid={`current-${city.city}`}>
        {Math.round(city.current_temp_f)}°F
      </span>
      <span className="text-[10px] flex items-center gap-1.5">
        <span className="text-red-400" data-testid={`high-${city.city}`}>
          H:{Math.round(city.today_high_f)}
        </span>
        <span className="text-blue-400" data-testid={`low-${city.city}`}>
          L:{Math.round(city.today_low_f)}
        </span>
      </span>
    </div>
  );
}

/**
 * Horizontal weather ticker showing current temp + hi/lo for all market cities.
 *
 * Renders below each page title. Returns null on error or while loading
 * (non-critical decorative element — should never block page rendering).
 */
export default function WeatherTicker() {
  const { data, error } = useCurrentWeather();

  // Don't render anything on error or before data loads
  if (error || !data || data.cities.length === 0) {
    return null;
  }

  return (
    <div
      className="flex items-center gap-1 overflow-x-auto bg-gradient-to-r from-slate-800 to-slate-900 rounded-lg px-3 py-2 mb-4 shadow-sm"
      data-testid="weather-ticker"
    >
      <Cloud size={14} className="text-slate-400 shrink-0" />
      <div className="flex items-center gap-3 divide-x divide-slate-600">
        {data.cities.map((city) => (
          <div key={city.city} className="pl-3 first:pl-0">
            <CityWeather city={city} />
          </div>
        ))}
      </div>
    </div>
  );
}
