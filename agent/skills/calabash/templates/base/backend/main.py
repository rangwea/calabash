"""Register typed local endpoints; keep business work out of module imports."""
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.logger import get_logger

logger = get_logger(__name__)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=200)


class MessageResult(BaseModel):
    message: str


def setup(app, sdk):
    @app.post('/api/message', operation_id='create_message', response_model=MessageResult)
    def create_message(payload: MessageInput) -> MessageResult:
        try:
            return MessageResult(message=payload.text.strip() or '你好')
        except Exception as error:
            # Do not include request contents in logs or user-facing errors.
            logger.exception('create_message failed')
            raise HTTPException(status_code=500, detail='暂时无法完成，请重试或让 AI 帮你修复') from error
