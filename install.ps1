# ============================================================================
#  Image Hunter — автоматический установщик для Windows
#
#  Установка одной строкой (PowerShell) — для ПУБЛИЧНОГО репозитория:
#    irm https://codeload.github.com/teliy/image-hunter/zip/refs/heads/main -OutFile "$env:TEMP\ih.zip"; Expand-Archive "$env:TEMP\ih.zip" "$env:TEMP\ih-src" -Force; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ih-src\image-hunter-main\install.ps1"
#  ВАЖНО: 1) не заменяйте это на "irm ... | iex" — PowerShell 5.1 при iex ломается на
#  BOM-символе (кириллица) и разборе param(); 2) не качайте установщик с raw.githubusercontent
#  сразу после коммита — raw кэшируется CDN на 5 минут (max-age=300) и query-параметры
#  игнорируются; codeload генерирует zip на лету и всегда свежий.
#
#  Для ПРИВАТНОГО репозитория (raw.githubusercontent отдаёт 404 без токена):
#    $t="ghp_xxx"; iwr https://raw.githubusercontent.com/teliy/image-hunter/main/install.ps1 -Headers @{Authorization="token $t"} -UseBasicParsing -OutFile "$env:TEMP\ih-install.ps1"; $env:IH_GH_TOKEN=$t; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ih-install.ps1"
#
#  Параметры: -InstallDir <путь>  -Update  -Uninstall  -Token <ghp_...>  -AssumeYes
# ============================================================================
#Requires -Version 5.1
param(
  [string]$InstallDir = $env:IH_DIR,
  [switch]$Update,
  [switch]$Uninstall,
  [string]$Token = $env:IH_GH_TOKEN,
  [switch]$AssumeYes
)

$ErrorActionPreference = 'Stop'
$Repo      = 'teliy/image-hunter'
$Branch    = 'main'
$AppName   = 'Image Hunter'
$DefaultDir = Join-Path $env:LOCALAPPDATA 'ImageHunter'

# нормализация параметров: пустые/пробельные строки → $null
# (иначе Join-Path падает на пустом пути, а неигнорируемые ошибки у нас Stop)
$InstallDir = if ($InstallDir) { $t = $InstallDir.Trim(); if ($t) { $t } else { $null } } else { $null }
$Token      = if ($Token)      { $t = $Token.Trim();      if ($t) { $t } else { $null } } else { $null }

# ---------------------------------------------------------------- утилиты
function Write-Step($msg)  { Write-Host "==> " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Write-Warn2($msg) { Write-Host "предупреждение: " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Write-Err2($msg)  { Write-Host "ошибка: " -ForegroundColor Red -NoNewline; Write-Host $msg }

function Ask([string]$Prompt, [string]$Default) {
  if ($AssumeYes) { return $Default }
  $v = Read-Host -Prompt "$Prompt [$Default]"
  if ([string]::IsNullOrWhiteSpace($v)) { return $Default }
  return $v.Trim()
}

function Confirm2([string]$Prompt, [bool]$DefaultYes = $true) {
  if ($AssumeYes) { return $true }
  $hint = if ($DefaultYes) { 'Y/n' } else { 'y/N' }
  $v = Read-Host -Prompt "$Prompt [$hint]"
  if ([string]::IsNullOrWhiteSpace($v)) { return $DefaultYes }
  return ($v -match '^(y|Y|д|Д|да)$')
}

# запущен ли установщик из папки установки (а не из временного архива исходников):
# в этом случае ImageHunter.bat рядом может прямо сейчас выполняться в cmd
function Test-InPlace([string]$DirPath) {
  if (-not $PSCommandPath) { return $false }
  try {
    $d = [System.IO.Path]::GetFullPath($DirPath).TrimEnd('\')
    $p = [System.IO.Path]::GetFullPath($PSCommandPath)
    return ($p.StartsWith($d + '\', 'OrdinalIgnoreCase') -or ($p -ieq $d))
  } catch { return $false }
}

# ---------------------------------------------------------------- защита от "irm | iex"
# При запуске через "irm ... | iex" PowerShell 5.1 передаёт BOM-символ внутрь строки:
# ломается разбор param() и переменные получают мусорные значения (например $InstallDir
# становится строкой "False"). Разрешаем только запуск файлом — см. однострочник в README.
if (-not $PSCommandPath) {
  Write-Host ''
  Write-Err2 'Установщик запущен через irm | iex — так PowerShell 5.1 ломает разбор параметров.'
  Write-Host 'Скопируйте и вставьте в PowerShell эту строку ЦЕЛИКОМ:' -ForegroundColor Yellow
  Write-Host '  irm https://raw.githubusercontent.com/teliy/image-hunter/main/install.ps1 -OutFile "$env:TEMP\ih-install.ps1"; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ih-install.ps1"' -ForegroundColor Cyan
  return
}

# ---------------------------------------------------------------- python
function Get-ValidPython {
  $candidates = @()
  foreach ($name in @('py', 'python', 'python3')) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
  }
  foreach ($exe in $candidates) {
    try { $v = & $exe -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null } catch { continue }
    if (-not $v) { continue }
    $parts = $v.Split('.'); $major = [int]$parts[0]; $minor = [int]$parts[1]
    # 3.10–3.14: PySide6 6.11 официально поддерживает весь диапазон (cp310-abi3)
    if ($major -eq 3 -and $minor -ge 10 -and $minor -le 14) {
      Write-Step ("Найден Python {0} ({1})" -f $v, $exe)
      return $exe
    }
  }
  return $null
}

function Install-Python {
  Write-Step "Python 3.10–3.14 не найден — устанавливаю…"
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    & winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    # обновляем PATH текущей сессии
    $env:Path = "$env:Path;$env:LOCALAPPDATA\Programs\Python\Python312\;$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\"
  } else {
    Start-Process 'https://www.python.org/downloads/'
    Write-Err2 "winget не найден. Установите Python 3.10–3.14 (64-bit) с открытой страницы,"
    Write-Err2 "обязательно отметьте галочку 'Add python.exe to PATH', затем запустите установщик снова."
    exit 1
  }
}

# ---------------------------------------------------------------- скачивание
function Get-Source {
  $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("ih_" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  $zip = Join-Path $tmp 'repo.zip'

  $headers = @{}
  if ($Token) {
    $url = "https://api.github.com/repos/$Repo/zipball/$Branch"
    $headers['Authorization'] = "token $Token"
    $headers['Accept'] = 'application/vnd.github+json'
  } else {
    $url = "https://codeload.github.com/$Repo/zip/$Branch"
  }

  Write-Step "Скачиваю исходники $(if ($Token) { '(с токеном)' } else { '(публичный репозиторий)' })…"
  try {
    Invoke-WebRequest -Uri $url -OutFile $zip -Headers $headers -UseBasicParsing
  } catch {
    if (-not $Token -and -not $AssumeYes) {
      Write-Warn2 "Не удалось скачать (возможно, репозиторий приватный)."
      if (Confirm2 "Ввести токен GitHub для доступа к приватному репозиторию?" $false) {
        $script:Token = Read-Host -Prompt 'Токен'
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
        return Get-Source
      }
    }
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Write-Err2 "Не удалось скачать исходники. Проверьте интернет или токен."
    exit 1
  }

  Write-Step "Распаковываю…"
  Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp 'src')
  $src = (Get-ChildItem (Join-Path $tmp 'src') | Select-Object -First 1).FullName
  if (-not (Test-Path (Join-Path $src 'main.py'))) {
    Write-Err2 "В архиве нет main.py — неожиданное содержимое"
    exit 1
  }
  return @($src, $tmp)
}

function Get-Ver([string]$root) {
  $f = Join-Path $root 'app\__init__.py'
  if (Test-Path $f) {
    $m = Select-String -Path $f -Pattern '__version__ = "(.*)"'
    if ($m) { return $m.Matches[0].Groups[1].Value }
  }
  return '?'
}

# ---------------------------------------------------------------- ярлык Пуска
function New-StartMenuShortcut([string]$dir) {
  try {
    $sm   = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    $lnk  = Join-Path $sm 'Image Hunter.lnk'
    $ws   = New-Object -ComObject WScript.Shell
    $sc   = $ws.CreateShortcut($lnk)
    $sc.TargetPath       = Join-Path $dir '.venv\Scripts\pythonw.exe'
    $sc.Arguments        = '"' + (Join-Path $dir 'main.py') + '"'
    $sc.WorkingDirectory = $dir
    # значок ярлыка — иконка приложения (многоразмерный ICO из ресурсов);
    # раньше ярлык указывал на иконку pythonw.exe — выглядело стандартно
    $ico = Join-Path $dir 'app\resources\app_icon.ico'
    $sc.IconLocation = if (Test-Path $ico) { "$ico,0" } else { (Join-Path $dir '.venv\Scripts\pythonw.exe') + ',0' }
    $sc.Save()
    Write-Step "Ярлык создан: меню Пуск → Image Hunter"
  } catch { Write-Warn2 "Не удалось создать ярлык: $_" }
}

# ---------------------------------------------------------------- основное действие
function Do-Install([string]$dir, [string]$mode) {   # mode: install | update | reinstall
  $oldVer = '?'
  if (Test-Path (Join-Path $dir 'app\__init__.py')) { $oldVer = Get-Ver $dir }

  $pair = Get-Source
  $src  = $pair[0]; $tmpRoot = $pair[1]
  $newVer = Get-Ver $src

  if ($mode -eq 'update') {
    Write-Step ("Обновление: {0} → {1}" -f $oldVer, $newVer)
    # ImageHunter.bat НЕ удаляем: из него мог быть запущен этот сеанс, а cmd
    # дочитывает батник уже после выхода PowerShell — если файл исчез,
    # сеанс падает с «Не удается найти пакетный файл»
    Get-ChildItem $dir -Force | Where-Object { $_.Name -notin @('.venv', '.gh_token', 'ImageHunter.bat') } |
      Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  }

  Write-Step "Копирую файлы в $dir …"
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
  Copy-Item -Path (Join-Path $src '*') -Destination $dir -Recurse -Force
  try {
    New-Item -ItemType Directory -Path (Join-Path $dir 'installer') -Force | Out-Null
    foreach ($f in @('install.ps1', 'install.sh')) {
      if (Test-Path (Join-Path $src $f)) { Copy-Item (Join-Path $src $f) (Join-Path $dir "installer\$f") -Force }
    }
    # если установщик запускали отдельным файлом и в исходниках его нет — кладём копию,
    # но НИКОГДА не копируем файл сам в себя (ошибка «не может перезаписать сам себя»)
    $dstPs1 = Join-Path $dir 'installer\install.ps1'
    if ($PSCommandPath -and -not (Test-Path $dstPs1)) {
      if ([System.IO.Path]::GetFullPath($PSCommandPath) -ine [System.IO.Path]::GetFullPath($dstPs1)) {
        Copy-Item $PSCommandPath $dstPs1 -Force
      }
    }
  } catch { Write-Warn2 "Не удалось обновить папку installer\: $_" }

  if ($Token) {
    [System.IO.File]::WriteAllText((Join-Path $dir '.gh_token'), $Token)
    Write-Warn2 "Токен сохранён в $dir\.gh_token (нужен для авто-обновлений). Удалите файл, если это нежелательно."
  }

  # venv
  $venvPy = Join-Path $dir '.venv\Scripts\python.exe'
  if (-not (Test-Path $venvPy)) {
    Write-Step "Создаю виртуальное окружение (.venv)…"
    & $Python -m venv (Join-Path $dir '.venv')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) {
      Write-Err2 "Не удалось создать виртуальное окружение"; exit 1
    }
  }
  Write-Step "Устанавливаю зависимости (1–2 минуты)…"
  & $venvPy -m pip install --upgrade pip --quiet
  & $venvPy -m pip install -r (Join-Path $dir 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { Write-Err2 "Не удалось установить зависимости"; exit 1 }

  # лаунчер
  $bat = @'
@echo off
setlocal
set "DIR=%~dp0"
if /I "%~1"=="update" (
  set "IH_DIR=%~dp0"
  powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%installer\install.ps1" -Update -AssumeYes
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="uninstall" (
  set "IH_DIR=%~dp0"
  powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%installer\install.ps1" -Uninstall
  exit /b %ERRORLEVEL%
)
if /I "%~1"=="version" (
  "%DIR%.venv\Scripts\python.exe" "%DIR%main.py" --version
  exit /b %ERRORLEVEL%
)
if not exist "%DIR%.venv\Scripts\pythonw.exe" (
  echo Installation is broken - run: "%DIR%ImageHunter.bat" update
  exit /b 1
)
start "" "%DIR%.venv\Scripts\pythonw.exe" "%DIR%main.py" %*
'@
  # лаунчер: не переписываем батник, из которого могли запустить этот сеанс
  # (свежая копия установщика уже легла в installer\ на шаге выше)
  $batPath = Join-Path $dir 'ImageHunter.bat'
  $oldBat  = $null
  if (Test-Path $batPath) { $oldBat = [System.IO.File]::ReadAllText($batPath) }
  $normNew = ($bat -replace "`r`n", "`n").Trim()
  $normOld = if ($null -ne $oldBat) { ($oldBat -replace "`r`n", "`n").Trim() } else { $null }
  if ($normOld -eq $normNew) {
    # лаунчер уже актуален — оставляем как есть
  } elseif ($null -eq $oldBat -or -not (Test-InPlace $dir)) {
    Set-Content -Path $batPath -Value $bat -Encoding ASCII
  } else {
    # установщик запущен из этой же папки (ImageHunter.bat update) — меняем файл
    # отложенно, чтобы не ломать текущий cmd-сеанс
    $batNew = Join-Path $dir 'ImageHunter.bat.new'
    Set-Content -Path $batNew -Value $bat -Encoding ASCII
    Start-Process cmd -ArgumentList '/c', "ping -n 3 127.0.0.1 >nul & move /y `"$batNew`" `"$batPath`"" -WindowStyle Hidden
    Write-Warn2 'Лаунчер ImageHunter.bat заменится через 2–3 секунды (сейчас файл используется этим окном).'
  }

  # ярлык: создаём при первой установке, если пропал, или если значок устарел
  # (ярлыки старых версий указывали на иконку pythonw.exe — обновляем их)
  $lnk = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Image Hunter.lnk'
  $staleIcon = $false
  if (Test-Path $lnk) {
    try {
      $old = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
      if ($old.IconLocation -notmatch 'app_icon\.ico') { $staleIcon = $true }
    } catch { $staleIcon = $true }
  }
  if ($mode -eq 'install') {
    if (-not (Test-Path $lnk) -or $staleIcon) {
      if (Confirm2 "Создать ярлык в меню «Пуск»?" $true) { New-StartMenuShortcut $dir }
    }
  } elseif (-not (Test-Path $lnk) -or $staleIcon) {
    New-StartMenuShortcut $dir
  }

  Remove-Item $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue

  Write-Host ''
  if ($mode -eq 'update') { Write-Step "$AppName $newVer обновлён: $dir" }
  else                    { Write-Step "$AppName $newVer установлен: $dir" }
  Write-Host '    Запуск:       ярлык «Image Hunter» или ImageHunter.bat'
  Write-Host '    Обновление:   ImageHunter.bat update'
  Write-Host '    Удаление:     ImageHunter.bat uninstall'
}

function Do-Uninstall([string]$dir) {
  if (-not (Confirm2 "Удалить $AppName из «$dir» (включая .venv)?" $false)) {
    Write-Host 'Отменено.'; exit 0
  }
  Write-Step 'Удаляю файлы…'
  Remove-Item (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Image Hunter.lnk') -Force -ErrorAction SilentlyContinue
  if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
  Write-Step 'Готово. Image Hunter удалён.'
}

# ---------------------------------------------------------------- main
Write-Host ''
Write-Host '════════════════════════════════════════' -ForegroundColor Green
Write-Host "   $AppName — установщик (Windows)"
Write-Host '════════════════════════════════════════' -ForegroundColor Green
Write-Host ''

Write-Step 'Ищу Python 3.10–3.14…'
$Python = Get-ValidPython
if (-not $Python) {
  Install-Python
  $Python = Get-ValidPython
  if (-not $Python) { Write-Err2 'Python не установился автоматически.'; exit 1 }
}

if ($Uninstall) {
  $d = if ($InstallDir) { $InstallDir } else { $DefaultDir }
  Do-Uninstall $d
  exit 0
}

$existsHere = $false
foreach ($d in @($DefaultDir, $InstallDir)) {
  if (-not $d) { continue }
  if (Test-Path (Join-Path $d 'main.py')) { $existsHere = $true; $FoundDir = $d; break }
}

# подхватываем токен, сохранённый прошлой установкой (для авто-обновлений приватного репо)
if (-not $Token) {
  foreach ($d in @($InstallDir, $DefaultDir)) {
    if (-not $d) { continue }
    $tf = Join-Path $d '.gh_token'
    if (Test-Path $tf) { $Token = (Get-Content $tf -Raw).Trim(); break }
  }
}

if ($existsHere) {
  if ($Update -or $AssumeYes) { Do-Install $FoundDir 'update'; exit 0 }
  Write-Host ''
  Write-Host "Найдена установленная копия: $FoundDir"
  Write-Host '  1) Обновить'
  Write-Host '  2) Переустановить заново'
  Write-Host '  3) Установить в другую папку'
  Write-Host '  4) Удалить'
  Write-Host '  0) Выйти'
  $choice = Ask 'Выберите действие' '1'
  switch ($choice) {
    '1' { Do-Install $FoundDir 'update' }
    '2' { Remove-Item $FoundDir -Recurse -Force; Do-Install (Ask 'Куда установить' $FoundDir) 'reinstall' }
    '3' { Do-Install (Ask 'Куда установить' $DefaultDir) 'install' }
    '4' { Do-Uninstall $FoundDir }
    default { Write-Host 'Отменено.' }
  }
  exit 0
}

# первая установка — спрашиваем место
if (-not $InstallDir) {
  Write-Host ''
  $InstallDir = Ask "Куда установить $AppName" $DefaultDir
}
Do-Install $InstallDir 'install'
