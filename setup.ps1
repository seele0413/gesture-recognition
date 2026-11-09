param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

function Find-Python {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
            throw "Python executable not found: $ExplicitPath"
        }
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }

    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        foreach ($Version in @("3.11", "3.12")) {
            $Resolved = & $Launcher.Source "-$Version" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $Resolved -and (Test-Path -LiteralPath $Resolved)) {
                return $Resolved.Trim()
            }
        }
    }

    throw "Install 64-bit Python 3.11 or 3.12, or pass its path with -PythonPath."
}

$SelectedPython = Find-Python -ExplicitPath $PythonPath
$VersionInfo = & $SelectedPython -c 'import sys,struct; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor)+chr(124)+str(struct.calcsize(chr(80))*8))'
if ($LASTEXITCODE -ne 0) { throw "Unable to run Python: $SelectedPython" }
$VersionParts = $VersionInfo.Trim().Split('|')
if ($VersionParts[0] -notin @("3.11", "3.12") -or $VersionParts[1] -ne "64") {
    throw "Detected Python $($VersionInfo.Trim()); use 64-bit Python 3.11 or 3.12."
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Creating a local virtual environment with Python $($VersionParts[0])..."
    & $SelectedPython -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the virtual environment." }
} else {
    $ExistingVersion = & $VenvPython -c 'import sys; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor))'
    if ($LASTEXITCODE -ne 0 -or $ExistingVersion.Trim() -notin @("3.11", "3.12")) {
        throw ".venv exists but has an unsupported Python version. Inspect and move it before retrying setup."
    }
    Write-Host "Reusing the existing Python $($ExistingVersion.Trim()) virtual environment."
}

Write-Host "Installing Python dependencies..."
& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check network access and Python version." }

Write-Host "Downloading and verifying vision models..."
& $VenvPython (Join-Path $ProjectRoot "scripts\download_models.py")
if ($LASTEXITCODE -ne 0) { throw "Model download failed. Restore network access and run setup.ps1 again." }

Write-Host "Setup complete. Run .\run.ps1 to start the website."
