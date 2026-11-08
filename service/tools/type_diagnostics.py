"""Extract bounded type evidence without returning source literals or raw logs."""
import re


def type_evidence(message: str) -> dict:
    evidence = {}
    mismatch = re.search(r"Type '(number|string|boolean|null|undefined|unknown|never)(\[\])?' is not assignable to type '(number|string|boolean|null|undefined|unknown|never)(\[\])?'", message)
    if mismatch:
        actual, actual_array, expected, expected_array = mismatch.groups()
        evidence.update(actual_type=actual + (actual_array or ''), expected_type=expected + (expected_array or ''))
    property_match = re.search(r"(?:Property|property) '([A-Za-z_$][A-Za-z0-9_$]{0,79})'", message)
    if property_match:
        evidence['property'] = property_match[1]
    return evidence
