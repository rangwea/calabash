/** Bounded ZIP transfer. The host validates source before user-confirmed installation. */
export type LibraryCall = (operation: string, args: Record<string, unknown>) => Promise<string>
const chunkSize = 192 * 1024
export const maxArchiveBytes = 8 * 1024 * 1024
export async function inspectArchive(call: LibraryCall, file: File): Promise<{ ticket: string; manifest: { project: string; name: string; title?: string; description?: string }; revision: string }> {
  if (!file.size || file.size > maxArchiveBytes) throw new Error('Invalid archive size')
  const { ticket } = JSON.parse(await call('begin', {})) as { ticket: string }
  try {
    for (let offset = 0; offset < file.size; offset += chunkSize) {
      const bytes = new Uint8Array(await file.slice(offset, offset + chunkSize).arrayBuffer())
      let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte)
      await call('upload', { ticket, offset, data: btoa(binary) })
    }
    return { ...JSON.parse(await call('inspect', { ticket })), ticket }
  } catch (error) { await call('discard', { ticket }).catch(() => undefined); throw error }
}
export async function exportArchive(call: LibraryCall, project: string, name: string): Promise<{ blob: Blob; name: string }> {
  const archive = JSON.parse(await call('export', { project, name })) as { ticket: string; size: number; name: string }
  try {
    if (archive.size < 1 || archive.size > maxArchiveBytes + 65536) throw new Error('Archive too large')
    const parts: Uint8Array<ArrayBuffer>[] = []
    for (let offset = 0; offset < archive.size;) {
      const value = JSON.parse(await call('read', { ticket: archive.ticket, offset })) as { data: string }
      const bytes = Uint8Array.from(atob(value.data), char => char.charCodeAt(0))
      if (!bytes.length || bytes.length > chunkSize || offset + bytes.length > archive.size) throw new Error('Invalid archive chunk')
      parts.push(bytes); offset += bytes.length
    }
    return { blob: new Blob(parts, { type: 'application/zip' }), name: archive.name }
  } finally { await call('discard', { ticket: archive.ticket }).catch(() => undefined) }
}
