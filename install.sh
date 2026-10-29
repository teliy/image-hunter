#!/usr/bin/env bash
# ============================================================================
#  Image Hunter — автоматический установщик для Linux / macOS
#
#  Установка одной строкой:
#    curl -fsSL https://raw.githubusercontent.com/teliy/image-hunter/main/install.sh | bash
#
#  Для приватного репозитория:
#    IH_GH_TOKEN=ghp_xxx bash -c "$(curl -fsSL https://raw.githubusercontent.com/teliy/image-hunter/main/install.sh)"
#
#  Неинтерактивный режим (все вопросы — по умолчанию):
#    IH_ASSUME_YES=1 bash install.sh
#  Переменные: IH_DIR=<папка установки>, IH_GH_TOKEN=<токен GitHub>
# ============================================================================
set -uo pipefail

REPO="teliy/image-hunter"
BRANCH="main"
APP_NAME="Image Hunter"
BIN_NAME="image-hunter"
DESKTOP_FILE="image-hunter.desktop"
DEFAULT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/image-hunter"

ASSUME_YES="${IH_ASSUME_YES:-0}"
TOKEN="${IH_GH_TOKEN:-}"
DIR="${IH_DIR:-}"
DO_UPDATE=0
DO_UNINSTALL=0

# ---------------------------------------------------------------- аргументы
while [ $# -gt 0 ]; do
  case "$1" in
    --dir)       DIR="${2:-}"; shift 2 ;;
    --update)    DO_UPDATE=1; shift ;;
    --uninstall) DO_UNINSTALL=1; shift ;;
    --yes|-y)    ASSUME_YES=1; shift ;;
    --token)     TOKEN="${2:-}"; shift 2 ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Неизвестный аргумент: $1 (см. --help)" >&2; exit 1 ;;
  esac
done

# ---------------------------------------------------------------- утилиты
C_G="\033[1;32m"; C_R="\033[1;31m"; C_Y="\033[1;33m"; C_0="\033[0m"
log()  { printf "${C_G}==>${C_0} %s\n" "$*"; }
warn() { printf "${C_Y}предупреждение:${C_0} %s\n" "$*"; }
err()  { printf "${C_R}ошибка:${C_0} %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

# ask ПЕРЕМЕННАЯ "Вопрос" "по_умолчанию"  — читает из /dev/tty (работает и при `curl | bash`)
ask() {
  local __var="$1" __prompt="$2" __def="${3:-}" __in=""
  if [ "$ASSUME_YES" = "1" ]; then
    printf -v "$__var" '%s' "$__def"; return 0
  fi
  if [ -r /dev/tty ]; then
    read -r -p "$__prompt [$__def]: " __in < /dev/tty || __in=""
  fi
  printf -v "$__var" '%s' "${__in:-$__def}"
}

# confirm "Вопрос" 0|1(умолчание) — 0 = да
confirm() {
  local __in=""
  if [ "$ASSUME_YES" = "1" ]; then return 0; fi
  if [ "${2:-1}" = "1" ]; then __in="" ; else __in="n"; fi
  local ans
  if [ -r /dev/tty ]; then
    read -r -p "$1 [$([ "${2:-1}" = "1" ] && echo "Y/n" || echo "y/N")]: " ans < /dev/tty || ans=""
  fi
  case "${ans:-$__in}" in
    ""|"y"|"Y"|"д"|"Д"|"да") return 0 ;;
    *) return 1 ;;
  esac
}

# ---------------------------------------------------------------- python
find_python() {
  local cand v major minor
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    command -v "$cand" >/dev/null 2>&1 || continue
    v="$("$cand" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)" || continue
    major="${v%%.*}"; minor="${v#*.}"
    if [ "$major" = "3" ] && [ "$minor" -ge 10 ] && [ "$minor" -le 13 ]; then
      printf '%s' "$cand"; return 0
    fi
  done
  return 1
}

install_python() {
  log "Python 3.10–3.13 не найден — пробую установить через пакетный менеджер…"
  local pkgs="python3 python3-venv python3-pip"
  local SUDO=""
  command -v sudo >/dev/null 2>&1 && [ "$(id -u)" != "0" ] && SUDO="sudo"
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y && $SUDO apt-get install -y $pkgs
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y python3
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -S --needed --noconfirm python
  elif command -v zypper >/dev/null 2>&1; then
    $SUDO zypper install -y python3
  else
    die "Не найден пакетный менеджер. Установите Python 3.10–3.13 вручную и запустите установщик снова."
  fi
}

ensure_venv() {  # $1 = python, $2 = путь venv
  if "$1" -m venv "$2" 2>/dev/null && [ -x "$2/bin/python" ]; then return 0; fi
  warn "venv без pip не создался — пробую --without-pip + get-pip.py"
  "$1" -m venv --without-pip "$2" || die "Не удалось создать виртуальное окружение"
  local gp="$2/get-pip.py"
  fetch "https://bootstrap.pypa.io/get-pip.py" "$gp" || die "Не удалось скачать get-pip.py"
  "$2/bin/python" "$gp" --quiet || die "Не удалось установить pip"
  rm -f "$gp"
}

ensure_gui_libs() {  # Qt ≥6.5 на Linux требует libxcb-cursor
  ldconfig -p 2>/dev/null | grep -q libxcb-cursor && return 0
  warn "Отсутствует libxcb-cursor (нужна для окна приложения) — пробую доустановить…"
  local SUDO=""
  command -v sudo >/dev/null 2>&1 && [ "$(id -u)" != "0" ] && SUDO="sudo"
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get install -y libxcb-cursor0 2>/dev/null || warn "Установите пакет libxcb-cursor0 вручную"
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y xcb-util-cursor 2>/dev/null || warn "Установите пакет xcb-util-cursor вручную"
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -S --needed --noconfirm xcb-util-cursor 2>/dev/null || warn "Установите пакет xcb-util-cursor вручную"
  fi
}

# ---------------------------------------------------------------- сеть
fetch() {  # fetch <url> <файл> [токен]
  local url="$1" out="$2"
  if [ -n "${3:-}" ]; then
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL -H "Authorization: token $3" -H "Accept: application/vnd.github+json" -o "$out" "$url"
    else
      wget -q --header="Authorization: token $3" --header="Accept: application/vnd.github+json" -O "$out" "$url"
    fi
  else
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL -o "$out" "$url"
    elif command -v wget >/dev/null 2>&1; then
      wget -q -O "$out" "$url"
    else
      "${PYTHON:-python3}" - "$url" "$out" <<'PYEOF'
import sys, urllib.request
urllib.request.urlretrieve(sys.argv[1], sys.argv[2])
PYEOF
    fi
  fi
}

download_source() {  # при успехе устанавливает глобальную SRC_DIR, иначе — ненулевой код
  local tmp zip url
  tmp="$(mktemp -d /tmp/image-hunter.XXXXXX)"
  zip="$tmp/repo.zip"
  if [ -n "$TOKEN" ]; then
    url="https://api.github.com/repos/$REPO/zipball/$BRANCH"
  else
    url="https://codeload.github.com/$REPO/zip/$BRANCH"
  fi
  log "Скачиваю исходники ($([ -n "$TOKEN" ] && echo "с токеном" || echo "публичный репозиторий"))…"
  if ! fetch "$url" "$zip" "$TOKEN"; then
    rm -rf "$tmp"
    if [ -z "$TOKEN" ] && [ "$ASSUME_YES" != "1" ]; then
      warn "Не удалось скачать (возможно, репозиторий приватный)."
      if confirm "Ввести токен GitHub для доступа к приватному репозиторию?" 0; then
        ask TOKEN "Токен" ""
        download_source; return
      fi
    fi
    err "Не удалось скачать исходники. Проверьте интернет или токен."
    return 1
  fi
  log "Распаковываю…"
  if ! "${PYTHON}" - "$zip" "$tmp" <<'PYEOF'
import sys, zipfile
zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])
PYEOF
  then
    rm -rf "$tmp"
    err "Ошибка распаковки архива"
    return 1
  fi
  SRC_DIR="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  if [ ! -f "$SRC_DIR/main.py" ]; then
    rm -rf "$tmp"
    err "В архиве нет main.py — неожиданное содержимое"
    return 1
  fi
}

ver_of() { sed -n 's/^__version__ = "\(.*\)"/\1/p' "$1/app/__init__.py" 2>/dev/null; }

# ---------------------------------------------------------------- действие: удалить
do_uninstall() {
  local d="$1"
  confirm "Удалить $APP_NAME из «$d» (включая .venv)?" 0 || { echo "Отменено."; exit 0; }
  log "Удаляю файлы…"
  rm -rf "$d"
  rm -f "$HOME/.local/bin/$BIN_NAME" "$HOME/.local/share/applications/$DESKTOP_FILE"
  log "Готово. $APP_NAME удалён."
}

# ---------------------------------------------------------------- действие: установка/обновление
do_install() {
  local d="$1" mode="$2"   # mode: install | update | reinstall
  local old_ver=""
  [ -f "$d/app/__init__.py" ] && old_ver="$(ver_of "$d")"

  local src new_ver
  download_source || die "Скачивание не удалось"
  src="$SRC_DIR"
  new_ver="$(ver_of "$src")"

  if [ "$mode" = "update" ]; then
    log "Обновление: ${old_ver:-?} → ${new_ver:-?}"
    find "$d" -mindepth 1 -maxdepth 1 ! -name '.venv' ! -name '.gh_token' -exec rm -rf {} +
  fi

  log "Копирую файлы в $d …"
  mkdir -p "$d"
  cp -a "$src/." "$d/"
  mkdir -p "$d/installer"
  cp -f "$src/install.sh" "$d/installer/install.sh" 2>/dev/null || true
  cp -f "$src/install.ps1" "$d/installer/install.ps1" 2>/dev/null || true
  rm -rf "$(dirname "$src")"

  [ -n "$TOKEN" ] && printf '%s' "$TOKEN" > "$d/.gh_token" && chmod 600 "$d/.gh_token"

  # venv
  if [ ! -x "$d/.venv/bin/python" ]; then
    log "Создаю виртуальное окружение (.venv)…"
    ensure_venv "$PYTHON" "$d/.venv" || die "Сбой создания venv"
  fi
  log "Устанавливаю зависимости (это может занять 1–2 минуты)…"
  "$d/.venv/bin/python" -m pip install --upgrade pip --quiet || true
  "$d/.venv/bin/python" -m pip install -r "$d/requirements.txt" || die "Не удалось установить зависимости"

  # лаунчер
  install_launcher "$d"
  maybe_desktop_entry "$d"

  echo
  if [ "$mode" = "update" ]; then
    log "$APP_NAME ${new_ver:-} обновлён: $d"
  else
    log "$APP_NAME ${new_ver:-} установлен: $d"
  fi
  echo "    Запуск:        $HOME/.local/bin/$BIN_NAME"
  echo "    Обновление:    $BIN_NAME update"
  echo "    Удаление:      $BIN_NAME uninstall"
  command -v "$HOME/.local/bin/$BIN_NAME" >/dev/null 2>&1 || true
}

install_launcher() {
  local d="$1" path="$HOME/.local/bin/$BIN_NAME"
  mkdir -p "$HOME/.local/bin"
  cat > "$path" <<LAUNCHER
#!/usr/bin/env bash
# Image Hunter launcher (создан install.sh)
DIR="$d"
case "\${1:-}" in
  update)
    tmp="\$(mktemp /tmp/image-hunter-update.XXXXXX.sh)"
    cp "\$DIR/installer/install.sh" "\$tmp" 2>/dev/null || exit 1
    IH_DIR="\$DIR" IH_ASSUME_YES="\${IH_ASSUME_YES:-1}" bash "\$tmp" --update
    rm -f "\$tmp" ;;
  uninstall)
    IH_DIR="\$DIR" bash "\$DIR/installer/install.sh" --uninstall ;;
  --version|version)
    exec "\$DIR/.venv/bin/python" "\$DIR/main.py" --version ;;
  *)
    if [ ! -x "\$DIR/.venv/bin/python" ]; then
      echo "Установка повреждена — выполните: \$DIR/installer/install.sh" >&2
      exit 1
    fi
    exec "\$DIR/.venv/bin/python" "\$DIR/main.py" "\$@" ;;
esac
LAUNCHER
  chmod +x "$path"

  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *)
      warn "$HOME/.local/bin нет в PATH"
      if confirm "Добавить \$HOME/.local/bin в PATH (~/.bashrc и ~/.profile)?" 1; then
        for rc in "$HOME/.bashrc" "$HOME/.profile"; do
          [ -f "$rc" ] && ! grep -qs "\.local/bin" "$rc" && \
            printf '\n# added by Image Hunter installer\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
        done
        log "Перезапустите терминал, чтобы команда $BIN_NAME была доступна."
      fi ;;
  esac
}

maybe_desktop_entry() {
  local d="$1" entry="$HOME/.local/share/applications/$DESKTOP_FILE"
  [ "$ASSUME_YES" = "1" ] && { write_desktop "$d" "$entry"; return 0; }
  if confirm "Создать ярлык в меню приложений (.desktop)?" 1; then
    write_desktop "$d" "$entry"
  fi
}

write_desktop() {
  local d="$1" entry="$2"
  mkdir -p "$HOME/.local/share/applications"
  cat > "$entry" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Image Hunter
Comment=Просмотр изображений, поиск картинок и их скачивание
Exec=$d/.venv/bin/python $d/main.py
Path=$d
Terminal=false
Categories=Graphics;Viewer;
DESKTOP
  log "Ярлык создан: $entry"
}

# ---------------------------------------------------------------- main
echo
printf "${C_G}════════════════════════════════════════${C_0}\n"
printf "   %s — установщик (Linux)\n" "$APP_NAME"
printf "${C_G}════════════════════════════════════════${C_0}\n\n"

log "Ищу Python 3.10–3.13…"
if PYTHON="$(find_python)"; then
  log "Найден: $PYTHON ($($PYTHON -c 'import sys;print("%d.%d"%sys.version_info[:2])'))"
else
  install_python
  PYTHON="$(find_python)" || die "Python не установился автоматически."
fi
ensure_gui_libs

if [ "$DO_UNINSTALL" = "1" ]; then
  DIR="${DIR:-$DEFAULT_DIR}"
  do_uninstall "$DIR"; exit 0
fi

# существующая установка?
if [ -f "$DEFAULT_DIR/main.py" ] || [ -f "$DIR/main.py" ]; then
  local_dir="${DIR:-$DEFAULT_DIR}"
  # подхватываем токен прошлой установки (для авто-обновлений приватного репо)
  if [ -z "$TOKEN" ] && [ -f "$local_dir/.gh_token" ]; then
    TOKEN="$(cat "$local_dir/.gh_token")"
  fi
  if [ "$DO_UPDATE" = "1" ]; then
    do_install "$local_dir" update; exit 0
  fi
  if [ "$ASSUME_YES" = "1" ]; then
    do_install "$local_dir" update; exit 0
  fi
  echo
  echo "Найдена установленная копия: $local_dir"
  echo "  1) Обновить"
  echo "  2) Переустановить заново"
  echo "  3) Установить в другую папку"
  echo "  4) Удалить"
  echo "  0) Выйти"
  choice=""
  ask choice "Выберите действие" "1"
  case "$choice" in
    1) do_install "$local_dir" update ;;
    2) rm -rf "$local_dir"; ask DIR "Куда установить" "$local_dir"; do_install "$DIR" install ;;
    3) ask DIR "Куда установить" "$DEFAULT_DIR"; do_install "$DIR" install ;;
    4) do_uninstall "$local_dir" ;;
    *) echo "Отменено." ;;
  esac
  exit 0
fi

# первая установка (в т.ч. если --update, но ничего не установлено)
if [ "$DO_UPDATE" = "1" ] && [ "$ASSUME_YES" != "1" ]; then
  warn "Установленная копия не найдена — выполняю первую установку."
fi
if [ -z "$DIR" ]; then
  echo
  ask DIR "Куда установить $APP_NAME" "$DEFAULT_DIR"
fi
do_install "$DIR" install
