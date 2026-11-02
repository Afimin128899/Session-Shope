#!/usr/bin/env bash
# Ubuntu 24: install the existing bot + Mini App + HTTPS, preserving .env.
set -Eeuo pipefail
trap 'printf "Установка остановлена на строке %s. Проверьте сообщение выше.\n" "$LINENO" >&2' ERR

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
bot_service=""
skip_https=0
fresh=0

usage() {
  cat <<'HELP'
Session Shope / Mini App · Ubuntu 24

Запуск из каталога проекта:
  sudo bash install.sh

Параметры:
  --service NAME.service  Использовать конкретный существующий сервис бота.
  --skip-https            Настроить только бота и локальный Mini App, без Caddy.
  --fresh                 Создать локальную MariaDB и запросить данные бота на VPS.
  -h, --help              Показать справку.

Обычный режим сохраняет .env. Режим --fresh запрашивает данные бота на VPS.
Секреты не выводятся в консоль.
HTTPS: sbandsub.space, адрес VPS: 31.77.59.42.
HELP
}

fail() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --service)
      (($# >= 2)) || fail 'После --service укажите имя сервиса.'
      bot_service="$2"; shift 2 ;;
    --skip-https) skip_https=1; shift ;;
    --fresh) fresh=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Неизвестный параметр: $1" ;;
  esac
done
[[ $EUID -eq 0 ]] || fail 'Запустите sudo bash install.sh'
# Trusted operating-system metadata, never source the project's secret .env.
# shellcheck source=/etc/os-release
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.* ]] || fail 'Скрипт рассчитан на Ubuntu 24.'
[[ -d /run/systemd/system ]] || fail 'Нужен VPS с запущенным systemd.'
[[ -f "$project_dir/bot.py" && -f "$project_dir/miniapp/server.py" ]] || fail 'Загрузите весь обновлённый проект, а не один install.sh.'
[[ -z "$bot_service" || "$bot_service" =~ ^[a-zA-Z0-9_.@-]+\.service$ ]] || fail 'Имя сервиса должно иметь вид shop.service.'

# Read only non-secret service metadata. Do not output ExecStart or environment.
bot_service="$(python3 - "$project_dir" "$bot_service" <<'PY'
import importlib.util, sys
from pathlib import Path
root=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location('service_installer',root/'deploy/create_service.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
try:
    print(sys.argv[2] or module.discover_service(root) or '')
except ValueError as exc:
    raise SystemExit(str(exc))
except (OSError, module.subprocess.CalledProcessError):
    raise SystemExit('Не удалось прочитать systemd. Проверьте systemctl status и повторите установку.')
PY
)"
if [[ ! -f "$project_dir/.env" && -z "$bot_service" && $fresh -eq 0 ]]; then
  fail 'Нет .env и существующего сервиса. Сначала задайте рабочие BOT_TOKEN, TELEGRAM_API_ID/HASH и DB_* в .env на сервере.'
fi
if ((skip_https == 0)); then
  listeners="$(ss -H -ltnp '( sport = :80 or sport = :443 )')"
  while IFS= read -r listener; do
    [[ -z "$listener" || "$listener" == *'"caddy"'* ]] || fail 'Порт 80 или 443 уже занят другим приложением. Используйте --skip-https и существующий HTTPS-прокси.'
  done <<< "$listeners"
fi

printf '\n[1/4] Установка системных зависимостей\n'
export DEBIAN_FRONTEND=noninteractive
apt-get update
packages=(python3-venv ca-certificates curl restic mariadb-client)
if ((skip_https == 0)); then packages+=(caddy); fi
if ((fresh)); then packages+=(mariadb-server); fi
apt-get install -y "${packages[@]}"

printf '\n[2/4] Подготовка отдельного Python-окружения\n'
(
  umask 022
  python3 -m venv "$project_dir/.venv-miniapp"
  "$project_dir/.venv-miniapp/bin/python" -m pip install --disable-pip-version-check -r "$project_dir/requirements.txt"
  "$project_dir/.venv-miniapp/bin/python" -m pip check
)

if ((fresh)); then
  systemctl enable --now mariadb
  "$project_dir/.venv-miniapp/bin/python" "$project_dir/deploy/bootstrap_env.py" --project "$project_dir"
fi

printf '\n[3/4] Настройка systemd и запуск Mini App\n'
service_args=(--python "$project_dir/.venv-miniapp/bin/python")
if [[ -n "$bot_service" ]]; then service_args+=(--service "$bot_service"); fi
python3 "$project_dir/deploy/create_service.py" "${service_args[@]}"
# This endpoint contains only process status and version, no credentials.
curl --fail --silent --show-error --retry 25 --retry-delay 2 --retry-connrefused \
  --max-time 3 http://127.0.0.1:8080/api/health
printf '\n'

if ((skip_https)); then
  "$project_dir/.venv-miniapp/bin/python" "$project_dir/deploy/setup_backups.py" --project "$project_dir"
  printf '\nГотово: Mini App работает на 127.0.0.1:8080. HTTPS-прокси пропущен по --skip-https.\n'
  exit 0
fi

printf '\n[4/4] Настройка HTTPS для sbandsub.space\n'
caddy_main=/etc/caddy/Caddyfile
caddy_site=/etc/caddy/session-shope/sbandsub.space.caddy
import_line='import /etc/caddy/session-shope/*.caddy'
install -d -m 755 /etc/caddy/session-shope
# Preserve unrelated sites and custom settings for this domain.
if [[ -f "$caddy_site" ]] && ! cmp -s "$project_dir/deploy/Caddyfile.vps" "$caddy_site"; then
  fail "$caddy_site уже содержит другие настройки. Файл не изменён."
fi
if [[ -f "$caddy_main" ]] && grep -Eq '^[[:space:]]*([^#]*[[:space:]/,])?sbandsub[.]space([[:space:],{]|$)' "$caddy_main"; then
  fail 'В /etc/caddy/Caddyfile уже настроен sbandsub.space. Настройте существующий блок, файл не изменён.'
fi
backup_dir="$(mktemp -d /var/backups/session-shope.XXXXXX)"
if [[ -f "$caddy_main" ]]; then cp -p "$caddy_main" "$backup_dir/Caddyfile"; fi
site_existed=0
if [[ -f "$caddy_site" ]]; then cp -p "$caddy_site" "$backup_dir/site.caddy"; site_existed=1; fi
install -m 644 "$project_dir/deploy/Caddyfile.vps" "$caddy_site"
if ! grep -Fxq "$import_line" "$caddy_main"; then
  printf '\n%s\n' "$import_line" >> "$caddy_main"
fi
if ! python3 "$project_dir/deploy/caddy_protocols.py" --config "$caddy_main" || ! caddy validate --config "$caddy_main"; then
  if [[ -f "$backup_dir/Caddyfile" ]]; then cp -p "$backup_dir/Caddyfile" "$caddy_main"; else rm -f "$caddy_main"; fi
  if ((site_existed)); then cp -p "$backup_dir/site.caddy" "$caddy_site"; else rm -f "$caddy_site"; fi
  fail 'Конфигурация Caddy не прошла проверку, прежние файлы восстановлены.'
fi
if command -v ufw >/dev/null 2>&1 && LC_ALL=C ufw status | grep '^Status: active' >/dev/null; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi
systemctl enable caddy
caddy_state="$(systemctl show caddy --property=ActiveState --value)"
if [[ "$caddy_state" == reloading ]]; then
  systemctl kill --kill-whom=all --signal=SIGTERM caddy
fi
timeout 45 systemctl restart caddy
printf '\nПроверка публичного HTTPS…\n'
if ! curl --fail --silent --show-error --retry 5 --retry-delay 3 --max-time 10 https://sbandsub.space/api/health; then
  fail 'Бот и локальный Mini App запущены, но HTTPS пока недоступен. Проверьте A-запись sbandsub.space → 31.77.59.42, AAAA и доступность портов 80/443. Логи: journalctl -u caddy -n 50 --no-pager'
fi
printf '\nНастройка зашифрованных резервных копий…\n'
"$project_dir/.venv-miniapp/bin/python" "$project_dir/deploy/setup_backups.py" --project "$project_dir"
printf '\n\nГотово: https://sbandsub.space\nОткройте Mini App кнопкой «Магазин» в Telegram-боте.\n'
