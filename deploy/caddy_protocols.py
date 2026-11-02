#!/usr/bin/env python3
"""Disable optional HTTP/3 to avoid conflicting with other UDP 443 services."""
import argparse
from pathlib import Path
import re
import sys

OPTIONS = '{\n\tservers {\n\t\tprotocols h1 h2\n\t}\n}\n\n'


def configure(text):
    effective = '\n'.join(line for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#'))
    compact = re.sub(r'\s+', ' ', effective).strip()
    if compact.startswith('{ servers { protocols h1 h2 } }'):
        return text
    if effective.lstrip().startswith('{'):
        raise ValueError('В Caddyfile уже есть пользовательский глобальный блок. Добавьте в него servers { protocols h1 h2 }, сохранив остальные настройки.')
    return OPTIONS + text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('/etc/caddy/Caddyfile'))
    args = parser.parse_args()
    old = args.config.read_text()
    new = configure(old)
    if new != old:
        args.config.write_text(new)
    print('Caddy: HTTPS использует HTTP/1.1 и HTTP/2; UDP 443 не требуется.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else 'Не удалось обновить конфигурацию Caddy.', file=sys.stderr)
        sys.exit(1)
