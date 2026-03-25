"use client";

/**
 * Timezone context — provides the user's configured timezone to all components.
 *
 * Reads from the settings SWR cache. Returns undefined when settings haven't
 * loaded yet or when the user chose "Browser Default" (empty string).
 */

import { createContext, useContext } from "react";

import { useSettings } from "@/lib/hooks";

const TimezoneContext = createContext<string | undefined>(undefined);

export function TimezoneProvider({ children }: { children: React.ReactNode }) {
  const { data: settings } = useSettings();
  // Empty string means "browser default" → pass undefined so toLocaleString uses browser tz
  const tz = settings?.timezone || undefined;

  return <TimezoneContext.Provider value={tz}>{children}</TimezoneContext.Provider>;
}

/**
 * Get the user's configured timezone for date formatting.
 * Returns an IANA timezone string (e.g. "America/Chicago") or undefined for browser default.
 */
export function useTimezone(): string | undefined {
  return useContext(TimezoneContext);
}
