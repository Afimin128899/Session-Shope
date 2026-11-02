#!/usr/bin/env bash
# Recover Caddy after a failed HTTP/3 reload without stopping the bot.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { printf 'Запустите через sudo bash deploy/fix_https.sh\n' >&2; exit 1; }
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
backup_dir="$(mktemp -d /var/backups/session-shope-https.XXXXXX)"
cp -p /etc/caddy/Caddyfile "$backup_dir/Caddyfile"
if ! python3 "$project_dir/deploy/caddy_protocols.py" || ! caddy validate --config /etc/caddy/Caddyfile; then
  cp -p "$backup_dir/Caddyfile" /etc/caddy/Caddyfile
  printf 'Проверка конфигурации не пройдена, исходный файл восстановлен.\n' >&2
  exit 1
fi
systemctl enable caddy
state="$(systemctl show caddy --property=ActiveState --value)"
if [[ "$state" == reloading ]]; then
  # Only Caddy's processes: the unrelated UDP 443 owner stays untouched.
  systemctl kill --kill-whom=all --signal=SIGTERM caddy
fi
if ! timeout 45 systemctl restart caddy; then
  printf 'Не удалось перезапустить Caddy. Проверьте systemctl status caddy --no-pager -l\n' >&2
  exit 1
fi
systemctl is-active caddy
curl --fail --silent --show-error --retry 5 --retry-delay 3 --max-time 15 https://sbandsub.space/api/health
printf '\nHTTPS восстановлен: https://sbandsub.space\n'
