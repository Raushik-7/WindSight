import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

export interface CutoffState {
  /** Decision cutoff time of day, HH:MM (Europe/London). */
  time: string;
  /** Days relative to the delivery date: -1 = day before, 0 = delivery day. */
  offsetDays: -1 | 0;
}

interface CutoffContextValue extends CutoffState {
  setTime: (value: string) => void;
  setOffsetDays: (value: -1 | 0) => void;
}

const DEFAULT_STATE: CutoffState = { time: '12:00', offsetDays: -1 };

const CutoffContext = createContext<CutoffContextValue | null>(null);

/**
 * The decision cutoff is an analysis parameter, not a chart label: changing it
 * re-queries the backend and re-runs forecast selection. Keeping it in context
 * means the same policy is applied on every page.
 */
export function CutoffProvider({ children }: { children: ReactNode }) {
  const [time, setTime] = useState(DEFAULT_STATE.time);
  const [offsetDays, setOffsetDays] = useState<-1 | 0>(DEFAULT_STATE.offsetDays);

  const value = useMemo<CutoffContextValue>(
    () => ({ time, offsetDays, setTime, setOffsetDays }),
    [time, offsetDays],
  );

  return <CutoffContext.Provider value={value}>{children}</CutoffContext.Provider>;
}

export function useCutoff(): CutoffContextValue {
  const context = useContext(CutoffContext);
  if (!context) {
    throw new Error('useCutoff must be used inside a CutoffProvider');
  }
  return context;
}

/** Query parameters for API calls. */
export function useCutoffParams(): { cutoff: string; cutoff_offset_days: number } {
  const { time, offsetDays } = useCutoff();
  return { cutoff: time, cutoff_offset_days: offsetDays };
}
