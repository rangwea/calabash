/** DSH owns persistence/timing; these presenters only format safe office-user views. */
const labels: Record<string, string> = {
  read_action_api: '查询办公能力', instructions: '了解工具编写规范', list_tools: '查看工具列表', read_ui_reference: '查阅工具规范',
  read_component_api: '查询组件用法', read_ui_preset: '选择界面风格', read_tool_template: '获取基础模板',
  read_tool: '查看工具文件', read_tool_file: '读取工具代码', write_tool_file: '保存工具草稿',
  patch_tool_file: '调整工具', check_tool_build: '检查工具', read_build_diagnostics: '查看检查结果',
  read_api_contract: '查询接口类型', read_preview_diagnostics: '检查页面与接口',
}
export const operations = Object.keys(labels)

export function callPresentation(args: { operation: string }) {
  return { card: 'generic' as const, title: labels[args.operation] ?? '处理工具', kind: 'other' as const }
}
export function resultPresentation(args: { operation: string }, result: { isError: boolean; content: readonly { type: string; text?: string }[] }) {
  let summary = '此步骤已完成'
  if (result.isError) summary = '此步骤未完成，请根据问题调整后重试'
  else {
    // Never interpolate untrusted source, paths, exception text or compiler output.
    let value: Record<string, unknown> = {}
    try {
      const text = result.content.find(block => block.type === 'text')?.text
      const parsed: unknown = text ? JSON.parse(text) : null
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) value = parsed as Record<string, unknown>
    } catch { /* Unknown result shapes still receive a safe summary. */ }
    if (value.error) summary = '此步骤未完成，请先处理当前问题'
    else if (args.operation === 'write_tool_file' || args.operation === 'patch_tool_file') {
      summary = value.saved === true ? '草稿已保存，尚未运行验证' : '草稿尚未保存，请检查后重试'
    } else if (args.operation === 'read_preview_diagnostics') {
      summary = value.state === 'passed' ? '页面与接口登记已检查，业务功能仍需试用' : value.state === 'failed' ? '发现页面或接口问题，可以继续调整' : value.state === 'stale' ? '工具已修改，请刷新预览后再检查' : '页面检查尚未就绪，请等待或打开预览'
    } else if (args.operation === 'check_tool_build' || args.operation === 'read_build_diagnostics') {
      summary = value.state === 'passed' ? '检查通过，请打开预览试用' : value.state === 'failed' ? '工具还需调整，可以让 AI 继续修复' : '检查结果尚未就绪'
    }
  }
  return { card: 'generic' as const, title: callPresentation(args).title, content: [{ type: 'text' as const, text: summary }] }
}
