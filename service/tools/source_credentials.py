"""Per-session source credential placeholders; replacement maps stay in memory."""

import hashlib
import re

# One shared definition: authoring redaction and export scrubbing must agree.
PATTERN = r'''(?i)(?:api[_-]?key|password|secret|access[_-]?token|authorization)[\w-]*["']?\s*[:=]\s*["']([^"'\r\n]{3,})["']'''
PLACEHOLDER = 'REDACTED_CREDENTIAL_'


def secret_placeholder(secret):
    return PLACEHOLDER + hashlib.sha256(secret.encode()).hexdigest()[:20]


class SourceCredentials:
    def __init__(self):
        self.values = {}

    def redact(self, content):
        secrets = [match.group(1) for match in re.finditer(PATTERN, content)]
        for secret in sorted(set(secrets), key=len, reverse=True):
            self.values[secret_placeholder(secret)] = secret
            content = content.replace(secret, secret_placeholder(secret))
        return content

    def restore(self, content):
        for placeholder in re.findall(r'REDACTED_CREDENTIAL_[a-f0-9]+', content):
            if placeholder not in self.values:
                raise ValueError('Credential placeholder expired; read current code again')
        for placeholder, secret in self.values.items():
            content = content.replace(placeholder, secret)
        return content


def strip_credentials(content):
    """Replace every detected secret with a stable placeholder without keeping it.

    Used on outbound copies (ZIP export) where the replacement map must not survive.
    An existing placeholder is not a secret: re-scrubbing must be idempotent.
    """
    secrets = {match.group(1) for match in re.finditer(PATTERN, content)}
    secrets = {secret for secret in secrets if not secret.startswith(PLACEHOLDER)}
    for secret in sorted(secrets, key=len, reverse=True):
        content = content.replace(secret, secret_placeholder(secret))
    return content
