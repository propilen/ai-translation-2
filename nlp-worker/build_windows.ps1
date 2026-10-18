param(
    [string]$Python = "",
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Python) { $Python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not $OutputDirectory) { $OutputDirectory = 'nlp-worker/dist' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python not found: $Python. Create the build venv and install requirements-build.txt and both spaCy models." }
if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) { throw 'Windows x64 and a 64-bit PowerShell process are required.' }
if ($env:OS -ne 'Windows_NT') { throw 'Run this script on Windows x64.' }

$check = @'
import importlib.metadata as m
import platform
import sys
expected = {'pymorphy3':'2.0.6', 'pymorphy3-dicts-ru':'2.4.417150.4580142', 'spacy':'3.8.16', 'en-core-web-sm':'3.8.0', 'de-core-news-sm':'3.8.0', 'Nuitka':'4.2.2'}
if sys.version_info[:2] != (3, 11) or platform.machine().lower() not in ('amd64', 'x86_64'):
    raise SystemExit('Build requires Python 3.11 x64')
for name, version in expected.items():
    try: actual = m.version(name)
    except m.PackageNotFoundError: raise SystemExit(f'Missing package: {name}=={version}')
    if actual != version: raise SystemExit(f'{name}: expected {version}, found {actual}')
import backend.nlp_glossary as nlp
for lang in ('ru','en','de'):
    nlp.init_nlp(lang)
    nlp.lemmatize('Fahrzeuge vehicles', lang)
    print(lang, 'model OK')
'@
Push-Location $projectRoot
try {
    $check | & $Python -
    if ($LASTEXITCODE -ne 0) { throw 'NLP dependency/model preflight failed.' }
    $arguments = @(
        '-m', 'nuitka', '--mode=standalone', '--assume-yes-for-downloads',
        ('--output-dir=' + $OutputDirectory), '--output-filename=nlp-worker.exe',
        '--spacy-language-model=en_core_web_sm', '--spacy-language-model=de_core_news_sm',
        '--include-module=backend.nlp_glossary',
        '--include-package=en_core_web_sm', '--include-package=de_core_news_sm',
        '--include-package=pymorphy3_dicts_ru',
        '--include-package-data=pymorphy3_dicts_ru',
        '--include-distribution-metadata=spacy',
        '--include-distribution-metadata=en_core_web_sm', '--include-distribution-metadata=de_core_news_sm',
        'nlp-worker/worker.py'
    )
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Nuitka failed with exit code $LASTEXITCODE" }
    $exe = Join-Path $OutputDirectory 'worker.dist\nlp-worker.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "Build completed without expected EXE: $exe" }
    $ping = '{"id":1,"action":"ping"}' | & $exe
    if ($LASTEXITCODE -ne 0 -or $ping -ne '{"id":1,"ok":true,"status":"ready"}') { throw "Built EXE failed ping smoke test: $ping" }
    $env:NLP_WORKER_EXE = (Resolve-Path -LiteralPath $exe).Path
    try {
        & $Python -B -m unittest discover -s nlp-worker/tests -v
        if ($LASTEXITCODE -ne 0) { throw "Built EXE regression tests failed with exit code $LASTEXITCODE" }
    }
    finally { Remove-Item Env:NLP_WORKER_EXE -ErrorAction SilentlyContinue }
    Write-Host "Built: $exe"
}
finally { Pop-Location }
