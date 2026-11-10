"""Versioned, bounded AI action contracts."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Parameters(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    @field_validator('*')
    @classmethod
    def output_filename(cls, value, info):
        if info.field_name == 'output_name' and (not value or value in {'.', '..'} or re.search(r'[/\\:\x00-\x1f<>"|?*]', value) or value.endswith(('.', ' '))):
            raise ValueError('Use a plain output filename')
        if info.field_name == 'output_name' and re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])', value.split('.')[0]):
            raise ValueError('Use a portable output filename')
        return value


class ActionRequest(Parameters):
    protocol_version: Literal[1] = 1
    action_version: Literal[1] = 1
    parameters: dict = Field(description='Parameters must match the selected action input schema.')


class ResultFile(Parameters):
    id: str
    name: str


class ActionResult(Parameters):
    protocol_version: Literal[1] = 1
    action_version: Literal[1] = 1
    invocation_id: str
    action_id: str
    outputs: list[ResultFile]
    counts: dict[str, int]


class ActionError(Parameters):
    code: str
    message: str


class ActionRun(Parameters):
    protocol_version: Literal[1] = 1
    action_version: Literal[1] = 1
    invocation_id: str
    action_id: str
    status: Literal['queued', 'running', 'succeeded', 'failed', 'cancelled']
    result: ActionResult | None = None
    error: ActionError | None = None


class ActionSubmission(Parameters):
    protocol_version: Literal[1] = 1
    action_version: Literal[1] = 1
    action_id: str
    invocation_ids: list[str]
    running: bool
    status: str
    progress: float
    counts: dict[str, int]


class AIParameters(Parameters):
    task: Literal['summarize', 'classify', 'extract', 'translate', 'generate']
    text: str = Field(min_length=1, max_length=20000, description='Exact text to send, shown in the host confirmation panel. Never add chat history or logs.')
    language: str = Field(default='', max_length=80, description='Required target language for translate.')
    labels: list[str] = Field(default_factory=list, max_length=30, description='For classify: 2–30 distinct labels, each up to 80 characters.')
    fields: dict[str, Literal['string', 'number', 'boolean']] = Field(default_factory=dict, max_length=20, description='For extract: required field names and scalar types; no expressions or code.')
    output_name: str = Field(default='ai-result', max_length=80, description='Plain filename stem; .txt or .json is added by the SDK.')

    @field_validator('labels')
    @classmethod
    def bounded_labels(cls, value):
        if len(set(value)) != len(value) or any(not label.strip() or len(label) > 80 for label in value):
            raise ValueError('Use distinct bounded labels')
        return value

    @field_validator('fields')
    @classmethod
    def bounded_fields(cls, value):
        if any(not re.fullmatch(r'[\w.-]{1,60}', name) for name in value):
            raise ValueError('Use plain field names')
        return value
