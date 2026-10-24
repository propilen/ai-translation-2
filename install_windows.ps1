[CmdletBinding()]
param(
    [string]$InstallPath = "C:\LinguaFlow",
    [string]$WorkspaceRoot = "C:\ai_trans",
    [string]$OkapiPath = "C:\LinguaFlow\Okapi",
    [switch]$ListenOnLan,
    [switch]$OpenFirewall
)

$ErrorActionPreference = "Stop"

# This script is intended to be run from an unpacked LinguaFlow distribution.
# It does not copy API keys or service-settings.json from the source computer.
$SourceRoot = Split-Path -Parent $PSCommandPath
$OkapiUrl = "https://okapiframework.org/binaries/main/1.48.0/okapi-apps_win32-x86_64_1.48.0.zip"

function Install-WingetPackage([string]$Id, [string]$Name) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Для установки $Name нужен winget. Установите $Name вручную и снова запустите скрипт."
    }
    Write-Host "Устанавливаем $Name..." -ForegroundColor Cyan
    & winget install --id $Id --exact --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Не удалось установить $Name через winget (код $LASTEXITCODE)."
    }
}

function Get-PythonCommand {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & py -3.11 --version | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return @{ File = "py"; Arguments = @("-3.11") }
        }
    }

    Install-WingetPackage "Python.Python.3.11" "Python 3.11"
    & py -3.11 --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 установлен, но launcher py пока недоступен. Откройте новое окно PowerShell и повторите запуск."
    }
    return @{ File = "py"; Arguments = @("-3.11") }
}

function Test-Java {
    $java = Get-Command java -ErrorAction SilentlyContinue
    if ($java) { return }
    Install-WingetPackage "Microsoft.OpenJDK.17" "Microsoft OpenJDK 17"
    if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
        Write-Warning "Java установлена, но не видна в текущем окне PowerShell. Перезапустите PowerShell перед первым запуском сервиса."
    }
}

function Copy-ApplicationFiles {
    $source = [System.IO.Path]::GetFullPath($SourceRoot)
    $target = [System.IO.Path]::GetFullPath($InstallPath)

    $requiredFiles = @(
        "run_server.py",
        "requirements.txt",
        "translate.html",
        "settings.html",
        (Join-Path "backend" "app.py")
    )
    $missingFiles = $requiredFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $source $_) -PathType Leaf) }
    if ($missingFiles) {
        $missingList = $missingFiles -join ", "
        throw "В папке с установщиком нет файлов сервиса: $missingList. Распакуйте полный комплект LinguaFlow в одну папку и запустите install_windows.ps1 из неё."
    }

    if ($source -eq $target) { return }
    if (Test-Path -LiteralPath $target) {
        $existing = Get-ChildItem -LiteralPath $target -Force | Select-Object -First 1
        if ($existing) { throw "Папка установки не пуста: $target" }
    }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Write-Host "Копируем файлы сервиса..." -ForegroundColor Cyan
    & robocopy $source $target /E /XD ".venv" "__pycache__" ".git" /XF "*.docx" "*.tsv"
    if ($LASTEXITCODE -gt 7) { throw "Не удалось скопировать файлы сервиса (код robocopy $LASTEXITCODE)." }
}

function Install-Okapi {
    New-Item -ItemType Directory -Path $OkapiPath -Force | Out-Null
    $tikal = Get-ChildItem -LiteralPath $OkapiPath -Filter "tikal.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $tikal) {
        $archive = Join-Path $env:TEMP "okapi-apps_win32-x86_64_1.48.0.zip"
        Write-Host "Скачиваем Okapi Framework 1.48.0..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $OkapiUrl -OutFile $archive
        Expand-Archive -LiteralPath $archive -DestinationPath $OkapiPath -Force
        Remove-Item -LiteralPath $archive -Force
        $tikal = Get-ChildItem -LiteralPath $OkapiPath -Filter "tikal.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $tikal) { throw "После установки Okapi не найден tikal.exe в $OkapiPath" }
    return $tikal.FullName
}

function Write-StartScript([string]$TikalExe) {
    $hostAddress = if ($ListenOnLan) { "0.0.0.0" } else { "127.0.0.1" }
    $runner = Join-Path $InstallPath "start_linguaflow.bat"
    @"
@echo off
cd /d "$InstallPath"
set "TRANSLATION_WORKSPACE=$WorkspaceRoot"
set "TIKAL_EXE=$TikalExe"
set "LINGUAFLOW_HOST=$hostAddress"
set "LINGUAFLOW_PORT=8000"
".venv\Scripts\python.exe" run_server.py
"@ | Set-Content -LiteralPath $runner -Encoding Default
    return $runner
}

Write-Host "LinguaFlow: подготовка установки" -ForegroundColor Green
Copy-ApplicationFiles
Test-Java
$python = Get-PythonCommand

$venvPython = Join-Path $InstallPath ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Создаём виртуальное окружение..." -ForegroundColor Cyan
    $venvTarget = Join-Path $InstallPath ".venv"
    $venvArguments = @($python.Arguments) + @("-m", "venv", $venvTarget)
    & $python.File @venvArguments
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        throw "Не удалось создать виртуальное окружение Python."
    }
}

Write-Host "Устанавливаем Python-зависимости и языковые модели..." -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $InstallPath "requirements.txt")
& $venvPython -m spacy download en_core_web_sm
& $venvPython -m spacy download de_core_news_sm
& $venvPython -m spacy download ru_core_news_sm

$tikalExe = Install-Okapi
New-Item -ItemType Directory -Path $WorkspaceRoot -Force | Out-Null
$startScript = Write-StartScript $tikalExe

if ($OpenFirewall) {
    New-NetFirewallRule -DisplayName "LinguaFlow TCP 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private -ErrorAction Stop | Out-Null
}

Write-Host "`nУстановка завершена." -ForegroundColor Green
Write-Host "Запуск: $startScript"
if ($ListenOnLan) {
    Write-Host "Сервис будет слушать локальную сеть на порту 8000."
}
