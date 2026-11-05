"""Per-run private placeholders; never persist the replacement map in graph state."""

import hashlib
import re


class SourceCredentials:
    def __init__(self):
        self.values = {}

    def redact(self, content):
        from service.chat.model_providers import load
        secrets = [value.get('key') for value in load().get('connections', {}).values() if value.get('key')]
        pattern = r'''(?i)(?:api[_-]?key|password|secret|access[_-]?token|authorization)[\w-]*["']?\s*[:=]\s*["']([^"'\r\n]{3,})["']'''
        secrets += [match.group(1) for match in re.finditer(pattern, content)]
        for secret in sorted(set(secrets), key=len, reverse=True):
            placeholder = 'REDACTED_CREDENTIAL_' + hashlib.sha256(secret.encode()).hexdigest()[:20]
            self.values[placeholder] = secret
            content = content.replace(secret, placeholder)
        return content

    def restore(self, content):
        for placeholder in re.findall(r'REDACTED_CREDENTIAL_[a-f0-9]+', content):
            if placeholder not in self.values:
                raise ValueError('Credential placeholder expired; read current code again')
        for placeholder, secret in self.values.items():
            content = content.replace(placeholder, secret)
        return content
