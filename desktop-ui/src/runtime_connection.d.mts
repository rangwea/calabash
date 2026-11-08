export type RuntimeState = {state: 'ready' | 'starting' | 'unavailable' | 'closed' | 'unknown'; running: boolean | null; origin?: string}
export function createConnectionMonitor(
  request: (resource: string, options: RequestInit) => Promise<RuntimeState>,
  update: (state: RuntimeState) => void,
  interval?: number,
): {start: (resource: string, runtimeUrl: string) => void; stop: () => void}
