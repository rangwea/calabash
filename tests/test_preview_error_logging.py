import asyncio
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from ui.pages import preview
from service.tools import preview_service


class PreviewErrorLoggingTest(unittest.TestCase):
    def test_event_callback_exception_is_written_to_preview_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            preview_file = Path(temp_dir) / "preview.py"
            preview_file.write_text("def main():\n    pass\n", encoding="utf-8")

            preview_logger = MagicMock()
            callback_handlers = []
            run = MagicMock()
            run.id = 'a' * 32
            run.logger = preview_logger
            run.context.return_value = nullcontext()

            with (
                patch.object(
                    preview, "get_preview_file", return_value=str(preview_file)
                ),
                patch.object(
                    preview.tool_run_logs, "start", return_value=run
                ),
                patch.object(preview, "render_tool_shell", return_value=nullcontext()),
                patch.object(
                    preview.ui,
                    "on_exception",
                    side_effect=lambda handler: callback_handlers.append(handler),
                ),
            ):
                container = preview.ui.column()

                async def render():
                    with container, patch.object(preview.ui.context.client, "calabash_output_owner", None, create=True):
                        await preview._render_preview("fixed.demo.chart", "demo/chart")
                        self.assertEqual(("preview:fixed.demo.chart", None), preview.ui.context.client.calabash_output_owner)

                asyncio.run(render())

            run.attach_module.assert_called_once_with('preview_fixed_demo_chart_' + 'a' * 32)
            self.assertEqual(len(callback_handlers), 1)

            error = RuntimeError("button failed")
            callback_handlers[0](error)

            preview_logger.opt.assert_called_once_with(exception=error)
            preview_logger.opt.return_value.error.assert_called_once_with(
                "预览事件回调执行失败: RuntimeError: button failed"
            )

    def test_syntax_error_during_upload_is_written_to_preview_log(self):
        preview_logger = MagicMock()

        with patch.object(
            preview_service, "get_preview_logger", return_value=preview_logger
        ):
            result = preview_service.save_preview(
                preview_key="fixed.demo.broken",
                content="def main(:\n    pass",
                preview_type="fixed",
                url="/preview/demo/broken",
                username="demo",
                tool_name="broken",
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "invalid_syntax")
        preview_logger.error.assert_called_once_with(
            "预览代码校验失败: Python 语法错误: 第 1 行 - invalid syntax"
        )


if __name__ == "__main__":
    unittest.main()
