import asyncio
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nicegui import core, ui

from service.chat import ai_chat
from service.files import tool_outputs

SKILL = Path(__file__).resolve().parents[1] / "agent/skills/calabash"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TemplateContractTests(unittest.TestCase):
    def setUp(self):
        self.validator = load_module("calabash_validator", SKILL / "scripts/validate-tool.py")
        self.header = (SKILL / "references/simple-tool.py").read_text().split('"""', 2)[1]

    def source(self, body):
        return f'"""{self.header}"""\n{body}\nif __name__ == "__main__":\n    main()\n    ui.run()\n'

    def test_all_shipped_templates_pass_without_executing_source(self):
        for name in ("simple-tool.py", "query-tool.py", "file-tool.py"):
            with self.subTest(name=name):
                self.assertEqual([], self.validator.validate_source((SKILL / "references" / name).read_text()))
        source = self.source('from nicegui import ui\nraise RuntimeError("must not execute")\ndef main():\n    pass')
        self.assertEqual([], self.validator.validate_source(source))

    def test_shared_state_at_import_time_is_rejected_even_with_aliases(self):
        for statement in [
            "from component.tool_files import ToolFileInput as Inputs\ninputs = Inputs()",
            "from component import tool_results as results_ui\nresults = results_ui.ToolResults()",
            "from service.tools.tool_jobs import ToolJobs\nqueue = {'jobs': ToolJobs([])}",
            "from service.tools.tool_jobs import ToolTask as Task\noperation = Task()",
        ]:
            source = self.source(f"from nicegui import ui\n{statement}\ndef main():\n    pass")
            self.assertTrue(self.validator.validate_source(source), statement)

    def test_page_local_helpers_and_unrelated_classes_remain_valid(self):
        source = self.source('from nicegui import ui\nfrom component.tool_results import ToolResults\ndef main():\n    results = ToolResults()')
        self.assertEqual([], self.validator.validate_source(source))
        unrelated = self.source('from nicegui import ui\nclass ToolResults:\n    pass\ncustom = ToolResults()\ndef main():\n    pass')
        self.assertEqual([], self.validator.validate_source(unrelated))

    def test_capability_declaration_syntax_is_checked_without_installing(self):
        for declaration in ("media.ffmpeg", "media.ffmpeg>=9.0.2, document.ocr", ""):
            source = self.source("from nicegui import ui\ndef main(): pass")
            source = source.replace("requires:", "requires: " + declaration)
            self.assertEqual([], self.validator.validate_source(source))
        for declaration in ("media.ffmpeg,", "media.ffmpeg==9.0.2", "media.ffmpeg,media.ffmpeg", "https://example.test"):
            source = self.source("from nicegui import ui\ndef main(): pass").replace("requires:", "requires: " + declaration)
            self.assertTrue(any("requires" in error for error in self.validator.validate_source(source)))


class FileTemplateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.container = ui.column()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for module in (ai_chat, tool_outputs):
            patcher = patch.object(module, "app_dir", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_query_template_uses_shared_single_task_runner(self):
        template = load_module("calabash_query_lifecycle", SKILL / "references/query-tool.py")
        with patch.object(core, "loop", asyncio.get_running_loop()), self.container, patch.object(ui, "timer"):
            tool = template.DataQueryTool()
            tool.create_ui()

            async def io_bound(function, *args):
                self.assertTrue(tool.task.running)
                self.assertFalse(tool.keyword_input.enabled)
                self.assertFalse(tool.search_button.enabled)
                return function(*args)

            with patch.object(template.run, "io_bound", io_bound):
                await tool.search(reset_page=True)
            self.assertEqual("succeeded", tool.task.status)
            self.assertEqual(10, len(tool.rows))
            self.assertTrue(tool.keyword_input.enabled)
            self.assertFalse(tool.previous_button.enabled)

    async def test_simple_template_uses_shared_single_task_runner(self):
        template = load_module("calabash_simple_lifecycle", SKILL / "references/simple-tool.py")
        with patch.object(core, "loop", asyncio.get_running_loop()), self.container:
            template.main()
            name = next(element for element in self.container.descendants() if "name-input" in element._markers)
            submit = next(element for element in self.container.descendants() if "submit-button" in element._markers)
            name.set_value("Example")

            async def io_bound(function, *args):
                self.assertFalse(name.enabled)
                return function(*args)

            with patch.object(template.run, "io_bound", io_bound), patch.object(ui, "notify"):
                next(iter(submit._event_listeners.values())).handler(None)
                for _ in range(20):
                    await asyncio.sleep(0)
            self.assertTrue(name.enabled)
            table = next(element for element in self.container.descendants() if isinstance(element, ui.table))
            self.assertEqual("Example", table.rows[0]["name"])

    async def test_real_template_exports_and_retries_only_failed_item(self):
        from service.files import tool_inputs

        template = load_module("calabash_file_template", SKILL / "references/file-tool.py")
        valid = self.root / "source.csv"
        valid.write_text("team,amount\nA,10\n,\nB,20\n", encoding="utf-8")
        invalid = self.root / "invalid.csv"
        invalid.write_bytes(b"\xff")
        original = valid.read_bytes()
        inputs = [{"path": str(path), "name": path.name} for path in (valid, invalid)]
        selectors = []
        real_selector = template.ToolFileInput

        def make_selector():
            selector = real_selector()
            selectors.append(selector)
            return selector

        async def io_bound(function, *args):
            self.assertTrue(selectors[0].frozen)
            self.assertFalse(selectors[0].clear())
            return await asyncio.to_thread(function, *args)

        with patch.object(core, "loop", asyncio.get_running_loop()), patch.object(template.run, "io_bound", io_bound), patch.object(template.logger, "exception") as logged, patch.object(tool_inputs, "current_inputs", return_value=inputs), self.container, patch.object(ui.context.client, "calabash_output_owner", ("tool:test/file-template", None), create=True):
            with patch.object(template, "ToolFileInput", make_selector):
                template.main()
            start = next(element for element in self.container.descendants() if "file-tool-start" in element._classes)
            outputs = tool_outputs.ToolOutputs(owner=("tool:test/file-template", None))

            async def click_and_wait(button, count):
                next(iter(button._event_listeners.values())).handler(None)
                for _ in range(300):
                    await asyncio.sleep(0.01)
                    if start.enabled and len(outputs.files()) == count:
                        return
                self.fail("Template callback did not finish")

            await click_and_wait(start, 1)
            first = outputs.files()
            self.assertEqual(1, len(first))
            with outputs.path(first[0]["id"]).open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual([{"team": "A", "amount": "10"}, {"team": "B", "amount": "20"}], list(csv.DictReader(handle)))
            self.assertTrue(start.enabled)
            self.assertFalse(selectors[0].frozen)
            selectors[0].clear()
            selectors[0].add_paths([valid])
            invalid.write_text("team,amount\nC,30\n")
            retry = next(element for element in self.container.descendants() if isinstance(element, ui.button) and element._props.get("icon") == "replay")
            await click_and_wait(retry, 2)
            final = outputs.files()
            self.assertEqual(2, len(final))
            self.assertEqual(1, len({item["run_id"] for item in final}))
            self.assertIn(first[0]["id"], [item["id"] for item in final])
            self.assertEqual(original, valid.read_bytes())
            self.assertTrue(start.enabled)
            self.assertFalse(selectors[0].frozen)
            self.assertEqual([str(valid)], selectors[0].paths)
            logged.assert_called_once_with("CSV processing failed")

    async def test_cancellation_keeps_inputs_locked_until_active_writer_finishes(self):
        from service.files import tool_inputs

        template = load_module("calabash_cancel_template", SKILL / "references/file-tool.py")
        sources = [self.root / name for name in ("first.csv", "second.csv")]
        for source in sources:
            source.write_text("name\nexample\n")
        selectors, statuses = [], []
        real_selector, real_status = template.ToolFileInput, template.ToolJobStatus
        entered, release = asyncio.Event(), asyncio.Event()

        def make_selector():
            selector = real_selector()
            selectors.append(selector)
            return selector

        class RecordingStatus(real_status):
            def __init__(self, jobs):
                super().__init__(jobs)
                statuses.append(self)

        async def io_bound(function, *args):
            entered.set()
            await release.wait()
            return await asyncio.to_thread(function, *args)

        records = [{"path": str(source)} for source in sources]
        with patch.object(core, "loop", asyncio.get_running_loop()), self.container, patch.object(tool_inputs, "current_inputs", return_value=records), patch.object(template, "ToolFileInput", make_selector), patch.object(template, "ToolJobStatus", RecordingStatus), patch.object(template.run, "io_bound", io_bound):
            template.main()
            start = next(element for element in self.container.descendants() if "file-tool-start" in element._classes)
            next(iter(start._event_listeners.values())).handler(None)
            try:
                await asyncio.wait_for(entered.wait(), 2)
                statuses[0].cancel()
                self.assertTrue(selectors[0].frozen)
                self.assertFalse(start.enabled)
                self.assertFalse(selectors[0].clear())
            finally:
                release.set()
                for _ in range(300):
                    await asyncio.sleep(0.01)
                    if start.enabled:
                        break
            self.assertFalse(selectors[0].frozen)
            self.assertEqual(["succeeded", "cancelled"], [job.status for job in statuses[0].jobs.jobs])
