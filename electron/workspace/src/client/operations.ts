/** Re-query late outcomes without replaying an accepted host operation. */
export interface OperationWire {
  startOperation(kind: string, input: string, request: string): Promise<unknown>
  /** The host only answers a task to the scope that asked for it. */
  task(id: string, scope: string): Promise<unknown>
}
export function createOperations(wire: OperationWire, unwrap: (result: unknown) => string) {
  const pendingOperations = new Map<string, { request: string; task?: string }>()
  const operation = async (kind: string, args: Record<string, unknown>): Promise<string> => {
    const input = JSON.stringify(args), key = kind + ':' + input
    const scope = typeof args.session === 'string' ? `session:${args.session}`
      : typeof args.project === 'string' && typeof args.name === 'string' ? `tool:${args.project}/${args.name}` : 'library:import'
    let pending = pendingOperations.get(key)
    if (!pending) { pending = { request: crypto.randomUUID() }; pendingOperations.set(key, pending) }
    if (!pending.task) pending.task = unwrap(await wire.startOperation(kind, input, pending.request))
    // Transport failures retain the request/task identity. Retrying observes the same operation.
    for (;;) {
      const task = JSON.parse(unwrap(await wire.task(pending.task, scope))) as { state: string; result?: unknown; resultAvailable: boolean }
      if (task.state === 'succeeded' && task.resultAvailable) { pendingOperations.delete(key); return JSON.stringify(task.result) }
      if (['failed', 'interrupted'].includes(task.state) || task.state === 'succeeded' && !task.resultAvailable) { pendingOperations.delete(key); throw new Error('Operation did not complete; check current state before retrying') }
      await new Promise(resolve => setTimeout(resolve, 350))
    }
  }
  return operation
}
