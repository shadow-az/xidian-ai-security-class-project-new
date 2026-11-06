"""JSON extraction shared by the two research workflows."""

import json


def extract_json_from_output(output_text: str) -> dict:
    """Return the first complete JSON object in text, or an empty dictionary.

    Braces inside JSON strings are literals. A balanced but invalid candidate
    can be skipped; an unclosed outer candidate is never mined for inner objects.
    Schema validation remains the caller's responsibility.
    """
    start = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(output_text):
        if start is None:
            if char == "{":
                start = index
                depth = 1
            continue

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = output_text[start:index + 1]
                start = None
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

    return {}
