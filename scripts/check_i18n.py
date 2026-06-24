"""i18n coverage check.

Exit non-zero if `kk.json` or `en.json` are missing keys that exist in `ru.json`.

Run in CI:
    python scripts/check_i18n.py

Or in pre-commit:
    python scripts/check_i18n.py --strict  # exit on missing
"""
import argparse
import json
import sys
from pathlib import Path

LOCALES = ('ru', 'kk', 'en')
LOCALES_TO_CHECK = ('kk', 'en')
BASE_LOCALE = 'ru'


def flatten(data: dict, prefix: str = '') -> dict:
    """Flatten nested dict into `{key.path: value}` mapping."""
    out = {}
    for k, v in data.items():
        key = f'{prefix}.{k}' if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict', action='store_true', help='Exit non-zero on missing keys')
    parser.add_argument('--ci', action='store_true', help='CI mode (strict + non-tty)')
    args = parser.parse_args()

    locales_dir = Path('apps/web/src/i18n/locales')
    if not locales_dir.exists():
        print(f'ERROR: locales dir not found: {locales_dir}', file=sys.stderr)
        return 2

    base = json.loads((locales_dir / f'{BASE_LOCALE}.json').read_text(encoding='utf-8'))
    base_flat = flatten(base)
    base_keys = set(base_flat.keys())

    missing_per_locale: dict[str, list[str]] = {}
    for loc in LOCALES_TO_CHECK:
        try:
            data = json.loads((locales_dir / f'{loc}.json').read_text(encoding='utf-8'))
        except Exception as e:
            print(f'ERROR: failed to read {loc}.json: {e}', file=sys.stderr)
            return 2
        flat = flatten(data)
        loc_keys = set(flat.keys())
        missing = sorted(base_keys - loc_keys)
        if missing:
            missing_per_locale[loc] = missing
        # Also check empty values.
        empty_keys = sorted([k for k, v in flat.items() if v is None or v == ''])
        if empty_keys:
            print(f'WARN: {loc}.json has empty values for {len(empty_keys)} keys: {empty_keys[:10]}{"..." if len(empty_keys) > 10 else ""}')

    if not missing_per_locale:
        total = len(base_keys)
        print(f'OK: all {total} keys in {BASE_LOCALE}.json are translated in kk.json and en.json')
        return 0

    print('=' * 70)
    print(f'i18n coverage report (base: {BASE_LOCALE}.json, {len(base_keys)} keys)')
    print('=' * 70)
    for loc, missing in missing_per_locale.items():
        pct = 100 * (len(base_keys) - len(missing)) / len(base_keys)
        print(f'  [{loc}] {len(missing)} missing ({pct:.1f}% coverage)')
        for m in missing[:30]:
            print(f'    - {m}')
        if len(missing) > 30:
            print(f'    ... and {len(missing) - 30} more')

    if args.strict or args.ci:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
