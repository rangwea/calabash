// Only host-authored, actionable messages reach the user. Never echo response bodies.
export function requestMessage(status, detail) {
  const known = {
    'Stop the running tool before replacing it': '工具正在处理任务，请完成后再保存',
    'Close the tool before deleting': '请先关闭这个工具，再删除',
    'Preview changed; inspect latest revision': '工具已更新，请刷新预览后再保存',
    'Preview changed during build': '工具已更新，请刷新预览后再保存',
    'Preview changed during publication': '工具已更新，请刷新预览后再保存',
    '当前版本检查失败，请先修复预览中的错误': '工具还需要调整，可以让 AI 帮你修复',
    'This revision failed validation. Fix the preview errors before saving.': '工具还需要调整，可以让 AI 帮你修复',
    'Conversation unavailable': '这段对话暂时无法打开，请返回后重试',
    'Source changed': '工具已更新，请刷新后再试',
    'Source changed; read current revision before writing': '工具已更新，请刷新后再试',
  }
  if (Object.hasOwn(known, detail)) return known[detail]
  if ([401, 403].includes(status)) return '连接已失效，请重新打开应用后重试'
  if (status === 404) return '内容暂时无法打开，请刷新后重试'
  if (status === 409) return '当前状态暂时无法完成此操作，请刷新后重试'
  if ([400, 413, 422].includes(status)) return '请检查填写的内容或所选文件后重试'
  if (status === 429) return '操作较多，请稍等片刻再试'
  return '暂时未能完成操作，请稍后重试'
}

export function displayError(message) {
  if (typeof message !== 'string' || /HTTP|TS\d{4}|Traceback|Request failed|SyntaxError|TypeError|ValueError|frontend\/|backend\//i.test(message)) return '暂时未能完成操作，请稍后重试'
  return message
}
