"""Register typed local endpoints; keep business work out of module imports."""
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.i18n import t
from core.logger import get_logger

logger = get_logger(__name__)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=200)


class MessageResult(BaseModel):
    message: str


def setup(app, sdk):
    with sdk.database(write=True) as db:
        db.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY CHECK(id = 1), text TEXT NOT NULL)')

    @app.post('/api/message', operation_id='create_message', response_model=MessageResult)
    def create_message(payload: MessageInput) -> MessageResult:
        try:
            message = payload.text.strip() or '你好'
            with sdk.database(write=True) as db:
                db.execute('INSERT INTO messages(id, text) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET text = excluded.text', (message,))
            return MessageResult(message=message)
        except Exception as error:
            # Do not include request contents in logs or user-facing errors.
            logger.exception('create_message failed')
            raise HTTPException(status_code=500, detail='暂时无法完成，请重试或让 AI 帮你修复') from error

    @app.get('/api/message', operation_id='read_message', response_model=MessageResult)
    def read_message() -> MessageResult:
        with sdk.database() as db:
            row = db.execute('SELECT text FROM messages WHERE id = 1').fetchone()
            return MessageResult(message=row['text'] if row else '')

    def export_saved_message():
        with sdk.database() as db:
            row = db.execute('SELECT text FROM messages WHERE id = 1').fetchone()
        if row is None:
            return
        output = sdk.output_path('saved-content.txt')
        output.write_text(row['text'], encoding='utf-8')
        return sdk.add_result(output)

    sdk.register_task('export_saved_message', t('导出已保存内容'), export_saved_message)
