"""Prevent context summaries from becoming executable tool source."""

import re


class SourcePlaceholderError(ValueError):
    pass


MARKERS = (
    '[Executed source omitted.',
    '[Executed source snapshot omitted.',
    '[Source snapshot omitted.',
    '[Virtual draft read omitted.',
    '[Snapshot omitted.',
    '[Source excerpt truncated for context.',
)


def reject_placeholders(content):
    if isinstance(content, str) and any(marker in content for marker in MARKERS):
        raise SourcePlaceholderError(
            'Context omission markers are not source code. Write was NOT applied. '
            'Use read_tool_file to read a small targeted page from the real working source, '
            'then patch only the relevant code. No staging or delivery step exists. '
            'Do not copy omission notices or numbered read output into source.'
        )


def validate_source_file(path, content):
    reject_placeholders(content)
    if path.endswith('.vue'):
        visible = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        if not re.search(r'<(?:template|script)(?:\s|/?>)', visible):
            raise ValueError(f'{path}: Vue source needs a template or script block. Source was not saved; write real component code.')
