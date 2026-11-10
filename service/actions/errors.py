"""Trusted AI action error categories; never expose request or model content."""
MESSAGES = {
    'ai_invalid_output': 'AI 返回的内容未符合要求，请调整后重试',
    'ai_expired': '本次确认已过期，请重新发起操作',
    'ai_declined': '本次 AI 操作已取消，未发送内容',
    'ai_failed': '本次 AI 操作未完成，请检查连接后手动重试',
    'unknown_action': '当前处理能力不可用，请选择其他操作',
    'unsupported_action_version': '当前处理能力版本不可用，请重新打开工具',
    'invalid_parameters': '请检查处理选项后重试',
    'processing_failed': '工具暂时未能完成操作，请重试或让 AI 帮你修复',
}


class ActionFailure(ValueError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'processing_failed'
        from core.i18n import t
        super().__init__(t(MESSAGES[self.code]))
