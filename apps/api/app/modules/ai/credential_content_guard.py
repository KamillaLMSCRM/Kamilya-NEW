"""Fail closed when response text could expose a configured credential."""
from __future__ import annotations

from json import JSONDecoder


def contains_credential(text: str, credential: str, *, embedded_json: bool = False) -> bool:
    """Inspect raw text and decoded JSON string tokens, including duplicate keys.

    Embedded JSON strings in the response envelope are inspected one layer deep.
    Malformed strings cannot establish safe custody.
    """
    if not credential:
        return False
    decoder = JSONDecoder()

    def inspect(value: str, depth: int) -> bool:
        if credential in value:
            return True
        position = 0
        while True:
            start = value.find('"', position)
            if start < 0:
                return False
            try:
                decoded, position = decoder.raw_decode(value, start)
            except (ValueError, UnicodeError):
                return True
            if credential in decoded:
                return True
            if embedded_json and depth == 0 and decoded == 'content':
                tail = value[position:].lstrip()
                if tail.startswith(':'):
                    tail = tail[1:].lstrip()
                    if tail.startswith('"'):
                        try:
                            nested, _ = decoder.raw_decode(tail)
                        except (ValueError, UnicodeError):
                            return True
                        if inspect(nested, depth + 1):
                            return True

    return inspect(text, 0)
