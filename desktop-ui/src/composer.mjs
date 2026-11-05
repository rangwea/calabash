export function shouldSend(event, state, now = performance.now()) {
  return event.key === 'Enter' && !event.shiftKey && !event.repeat && !event.isComposing && event.keyCode !== 229 && !state.composing && !state.uploading && (state.ended === undefined || now - state.ended >= 50)
}
