import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from service.capabilities.tool_capabilities import (
    Requirement,
    ToolCapabilityError,
    check_requirements,
    parse_requirements,
)


class RequirementTests(unittest.TestCase):
    def manager(self, state="ready", version="9.0.2"):
            return SimpleNamespace(selfchecks={"media.ffmpeg": Mock()},
                                   status=Mock(return_value={"state": state, "version": version}))

    def test_parse_optional_capability_declarations(self):
            self.assertEqual((), parse_requirements(""))
            self.assertEqual((Requirement("media.ffmpeg", "9.0.2"), Requirement("document.ocr")),
                             parse_requirements("media.ffmpeg >= 9.0.2, document.ocr"))
            self.assertEqual((), parse_requirements(""))

    def test_reject_malformed_duplicate_and_unbounded_declarations(self):
            for value in ("media.ffmpeg,media.ffmpeg", "media.ffmpeg,", "media.ffmpeg==9.0.2",
                          "media.ffmpeg>=9.0", "https://example.test/plugin.zip", "pandas",
                          "media.ffmpeg>=9999999.0.0", "a.b" * 1000):
                with self.subTest(value=value[:50]), self.assertRaises(ToolCapabilityError) as caught:
                    parse_requirements(value)
                self.assertTrue(caught.exception.invalid)

    def test_check_missing_corrupt_version_and_unsupported(self):
            requirement = (Requirement("media.ffmpeg", "9.0.2"),)
            for state, version, expected in (("not_installed", None, "missing"), ("invalid", None, "damaged"),
                                              ("ready", "9.0.1", "version"), ("ready", "10.0.0", None)):
                with self.subTest(state=state, version=version):
                    issues = check_requirements(requirement, self.manager(state, version))
                    self.assertEqual([expected] if expected else [], [issue.reason for issue in issues])
            manager = self.manager()
            self.assertEqual("unsupported", check_requirements((Requirement("document.ocr"),), manager)[0].reason)
            self.assertEqual("unsupported", check_requirements((Requirement("custom.engine"),), manager)[0].reason)
            manager.status.assert_not_called()
            manager.status.side_effect = OSError("broken")
            self.assertEqual("damaged", check_requirements(requirement, manager)[0].reason)
