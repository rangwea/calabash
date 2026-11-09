"""Closed built-in action registry; discovery never reads files or runs handlers."""
from collections.abc import Callable
from dataclasses import dataclass

from service.actions.models import ExcelParameters, WordParameters
from service.actions.office import excel_process, word_fill


@dataclass(frozen=True)
class Action:
    id: str
    title: str
    title_en: str
    parameters: type
    handler: Callable
    input_field: str
    extension: str
    limits: dict

    def describe(self):
        from service.actions.models import ActionResult, ActionRun, ActionSubmission
        return {'id': self.id, 'version': 1, 'protocol_version': 1, 'title': self.title, 'title_en': self.title_en,
                'execution': 'background', 'cancellation': 'after_current_action',
                'permissions': ['read_selected_files', 'create_result_files'],
                'network': False, 'overwrites_inputs': False,
                'input_schema': self.parameters.model_json_schema(), 'output_schema': ActionResult.model_json_schema(),
                'submission_schema': ActionSubmission.model_json_schema(), 'run_schema': ActionRun.model_json_schema(),
                'limits': self.limits}


_ACTIONS = (
    Action('office.excel.process', 'Excel 数据处理', 'Excel data processing', ExcelParameters, excel_process, 'input_ids', '.xlsx',
           {'rows': 20000, 'columns': 200, 'cells': 500000, 'formats': ['xlsx'], 'formulas': False, 'preserves_formatting': False}),
    Action('office.word.fill_template', 'Word 模板填充', 'Word template filling', WordParameters, word_fill, 'template_id', '.docx',
           {'characters': 1000000, 'replacements': 10000, 'formats': ['docx'], 'expressions': False, 'multiline_values': False}),
)


def get(action_id):
    for action in _ACTIONS:
        if action.id == action_id:
            return action
    from service.actions.office import ActionFailure
    raise ActionFailure('unknown_action')


def catalog():
    return {'protocol_version': 1, 'actions': [{key: value for key, value in action.describe().items() if not key.endswith('_schema')} for action in _ACTIONS]}


def describe(action_id=''):
    return get(action_id).describe() if action_id else catalog()
