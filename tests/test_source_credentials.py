"""Source redaction remains usable without any model configuration service."""
import unittest

from service.tools.source_credentials import SourceCredentials, strip_credentials


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

    def test_export_scrub_keeps_no_reversible_mapping(self):
        source = 'api_key = "synthetic-private-value"\npassword = "synthetic-password"'
        scrubbed = strip_credentials(source)
        self.assertNotIn('synthetic-private-value', scrubbed)
        self.assertNotIn('synthetic-password', scrubbed)
        self.assertIn('REDACTED_CREDENTIAL_', scrubbed)
        # Scrub is idempotent: a second pass must not invent new placeholders.
        self.assertEqual(scrubbed, strip_credentials(scrubbed))
