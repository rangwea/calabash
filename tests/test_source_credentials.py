"""Source redaction remains usable without any model configuration service."""
import unittest

from service.tools.source_credentials import SourceCredentials


class SourceCredentialTests(unittest.TestCase):
    def test_roundtrip_redacts_source_and_unknown_placeholders_fail_closed(self):
        credentials = SourceCredentials()
        source = 'API_KEY = "synthetic-private-value"\npassword = "synthetic-password"'
        redacted = credentials.redact(source)
        self.assertNotIn('synthetic-private-value', redacted)
        self.assertNotIn('synthetic-password', redacted)
        self.assertEqual(source, credentials.restore(redacted))
        with self.assertRaisesRegex(ValueError, 'expired'):
            SourceCredentials().restore(redacted)
