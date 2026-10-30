param(
    [ValidateSet('cu118','cu128','cpu')]
    [string]$Backend = 'cu118',
    [string]$Python = 'py',
    [switch]$SkipDependencies
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if ($Python -eq 'py') { & $Python -3.12 -m venv .venv }
    else { & $Python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create a Python 3.12 virtual environment.' }
}
& $venvPython -I -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 is required"'
if ($LASTEXITCODE -ne 0) { throw 'The virtual environment must use Python 3.12.' }
& $venvPython -I tools/configure_venv.py
if ($LASTEXITCODE -ne 0) { throw 'Could not register the project in the virtual environment.' }
if (-not $SkipDependencies) {
    if ($Backend -ne 'cpu') {
        $index = "https://download.pytorch.org/whl/$Backend"
        & $venvPython -I -m pip install "torch==2.7.1+$Backend" "torchaudio==2.7.1+$Backend" --index-url $index --extra-index-url https://pypi.org/simple
        if ($LASTEXITCODE -ne 0) { throw 'Torch installation failed.' }
    }
    & $venvPython -I -m pip install -r "requirments_${Backend}_py312.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
Write-Host 'Environment prepared. FFmpeg, model files and training silence assets are separate; see docs/INSTALLATION.md.'
