import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "agent/skills/calabash"


class BuiltinSkillTests(unittest.TestCase):
    def test_development_skill_links_to_builtin_source(self):
        root = SKILL.parents[2]
        self.assertTrue((root / ".agents/skills/calabash").is_symlink())
        self.assertEqual(SKILL, (root / ".agents/skills/calabash").resolve())
        self.assertIn("name: calabash", (SKILL / "SKILL.md").read_text())
        self.assertIn("Use $calabash", (SKILL / "agents/openai.yaml").read_text())
