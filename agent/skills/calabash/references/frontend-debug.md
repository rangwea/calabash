# 前端诊断和验收

用户在当前预览“诊断与验收”授权后，inspect_preview 返回有界的可见文字、控件 ID、媒体状态与浏览器错误，不含输入框值或截图。授权绑定当前会话、模型、页面和源码版本，有效十分钟；刷新或源码变化后需要重新授权。

interact_preview 用当前控件 ID 请求一次 click/fill；宿主逐次确认并展示目标、输入、目的及业务风险。拒绝、过期或结果未知时不得自动重试。真实写入、删除和导出必须核对本次操作后确认。

verify_preview 仅支持 text_visible、element_enabled、no_horizontal_overflow、no_frontend_errors、media_time_advances。最后一种必须观察媒体时间推进。记录检查结果和 revision，不把这些局部证据当成整个工具业务、视觉效果或真实音频输出已通过。

修复当前失败时先 read_tool，再 read_tool_logs 分页/字面搜索当前批准运行。修改后由用户手动刷新和重试，保存不代表已验证。
