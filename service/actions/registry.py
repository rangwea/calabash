"""Closed built-in action registry; discovery never reads files or runs handlers."""
from dataclasses import dataclass

from service.actions.models import AIParameters


@dataclass(frozen=True)
class Action:
    id: str
    title: str
    title_en: str
    parameters: type
    limits: dict

    def describe(self):
        from service.actions.models import ActionResult, ActionRun, ActionSubmission
        return {'id': self.id, 'version': 1, 'protocol_version': 1, 'title': self.title, 'title_en': self.title_en,
                'execution': 'background', 'cancellation': 'abort_before_result_write',
                'permissions': ['send_confirmed_text_to_selected_model', 'create_result_files'],
                'network': 'user_selected_model', 'overwrites_inputs': False,
                'input_schema': self.parameters.model_json_schema(), 'output_schema': ActionResult.model_json_schema(),
                'submission_schema': ActionSubmission.model_json_schema(), 'run_schema': ActionRun.model_json_schema(),
                'limits': self.limits}


_ACTIONS = (
    Action('ai.text', 'AI 文本处理', 'AI text processing', AIParameters,
           {'input_characters': 20000, 'output_characters': 32000, 'confirmation': 'each_request', 'model_tools': False, 'batch_requests': 1, 'max_output_tokens': 2048}),
)


def get(action_id):
    for action in _ACTIONS:
        if action.id == action_id:
            return action
    from service.actions.errors import ActionFailure
    raise ActionFailure('unknown_action')


def catalog():
    return {'protocol_version': 1, 'actions': [{key: value for key, value in action.describe().items() if not key.endswith('_schema')} for action in _ACTIONS]}


def describe(action_id=''):
    return get(action_id).describe() if action_id else catalog()
