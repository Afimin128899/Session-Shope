#!/usr/bin/env bash
# Run on a clean Ubuntu 24 VPS. Secrets are entered only on the VPS terminal.
set -Eeuo pipefail
trap 'printf "Установка остановлена на строке %s. Повторите эту же команду после исправления ошибки.\n" "$LINENO" >&2' ERR
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  printf 'Чистая Ubuntu 24: sudo bash install-fresh.sh\nПроект: /opt/session-shope. База: локальная MariaDB. HTTPS: sbandsub.space.\n'
  exit 0
fi
[[ $# -eq 0 ]] || { printf 'Неизвестный параметр. Используйте --help.\n' >&2; exit 1; }
[[ $EUID -eq 0 ]] || { printf 'Запустите через sudo bash install-fresh.sh\n' >&2; exit 1; }
# shellcheck source=/etc/os-release
source /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.* ]] || { printf 'Нужна Ubuntu 24.\n' >&2; exit 1; }
[[ -d /run/systemd/system ]] || { printf 'Нужен VPS с systemd.\n' >&2; exit 1; }
[[ -r /dev/tty && -w /dev/tty ]] || { printf 'Нужен интерактивный SSH-терминал для безопасного ввода данных бота.\n' >&2; exit 1; }
project_dir=/opt/session-shope
state_dir=/etc/session-shope
marker="$state_dir/project-created"
install -d -m 700 "$state_dir"
if [[ -e "$marker" ]]; then
  [[ $(cat "$marker") == "$project_dir" ]] || { printf 'Сохранён другой путь проекта. Файлы не изменены.\n' >&2; exit 1; }
elif [[ -e "$project_dir" ]]; then
  printf '%s уже существует. Для текущего проекта используйте install.sh.\n' "$project_dir" >&2
  exit 1
else
  (umask 077; printf '%s\n' "$project_dir" > "$marker")
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git ca-certificates curl python3-venv
if [[ ! -d "$project_dir/.git" ]]; then
  git clone --branch main --single-branch https://github.com/Afimin128899/Session-Shope.git "$project_dir"
else
  # A retry reuses the checkout and .env. Never reset or discard local files.
  printf 'Продолжаем установку из %s\n' "$project_dir"
fi
exec bash "$project_dir/install.sh" --fresh
