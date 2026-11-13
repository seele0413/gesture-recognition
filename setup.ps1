param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Get-PythonIdentity {
    param([string]$Executable)

    $Probe = & $Executable -c 'import json,struct,sys; print(json.dumps({"path":sys.executable,"major":sys.version_info.major,"minor":sys.version_info.minor,"bits":struct.calcsize("P")*8,"implementation":sys.implementation.name}))' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $Probe) {
        return $null
    }
    try {
        return (($Probe -join "`n").Trim() | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Find-Python {
    param([string]$ExplicitPath)

    $Candidates = @()
    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
            throw "Python executable not found: $ExplicitPath"
        }
        $Candidates += (Resolve-Path -LiteralPath $ExplicitPath).Path
    } else {
        $Launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($Launcher) {
            foreach ($Line in (& $Launcher.Source -0p 2>$null)) {
                $Match = [regex]::Match([string]$Line, '(?<path>[A-Za-z]:\\.*?pythonw?\.exe)\s*$', 'IgnoreCase')
                if ($Match.Success) {
                    $Candidates += $Match.Groups['path'].Value
                }
            }
        }
        foreach ($CommandName in @('python.exe', 'python')) {
            $Command = Get-Command $CommandName -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.CommandType -eq 'Application' -and
                    $_.Source -notmatch '\\Microsoft\\WindowsApps\\'
                } |
                Select-Object -First 1
            if ($Command) {
                $Candidates += $Command.Source
            }
        }
    }

    $Compatible = @()
    $Seen = @{}
    $Detected = @()
    foreach ($Candidate in $Candidates) {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            continue
        }
        $Resolved = (Resolve-Path -LiteralPath $Candidate).Path
        if ($Seen.ContainsKey($Resolved)) { continue }
        $Seen[$Resolved] = $true
        $Identity = Get-PythonIdentity -Executable $Resolved
        if (-not $Identity) { continue }

        $Version = "$($Identity.major).$($Identity.minor)"
        $IsCompatible = (
            $Identity.implementation -eq 'cpython' -and
            [int]$Identity.major -eq 3 -and
            [int]$Identity.minor -ge 10 -and
            [int]$Identity.minor -le 12 -and
            [int]$Identity.bits -eq 64
        )
        $Detected += "$Version/$($Identity.bits)-bit $($Identity.implementation)"
        if ($ExplicitPath -and -not $IsCompatible) {
            throw "Python $Version ($($Identity.bits)-bit $($Identity.implementation)) is incompatible with the pinned Windows wheels. Use 64-bit CPython 3.10, 3.11, or 3.12."
        }
        if ($IsCompatible) {
            $Compatible += [pscustomobject]@{
                Path = [string]$Identity.path
                Major = [int]$Identity.major
                Minor = [int]$Identity.minor
            }
        }
    }

    if ($Compatible.Count -gt 0) {
        return ($Compatible | Sort-Object @{Expression = 'Major'; Descending = $true}, @{Expression = 'Minor'; Descending = $true} | Select-Object -First 1)
    }

    $DetectedText = if ($Detected.Count) { $Detected -join ', ' } else { 'none found by py -0p or PATH' }
    throw "No compatible installed Python was found ($DetectedText). Current pinned dependencies require 64-bit CPython 3.10-3.12 on Windows. No Python will be downloaded; pass a compatible executable with -PythonPath."
}

# Reuse a compatible project environment before considering global interpreters.
if (-not $PythonPath -and (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    $SelectedPython = Find-Python -ExplicitPath $VenvPython
    $SelectedSource = "existing .venv"
} else {
    $SelectedPython = Find-Python -ExplicitPath $PythonPath
    $SelectedSource = "installed interpreter"
}

$SelectedVersion = "$($SelectedPython.Major).$($SelectedPython.Minor)"
Write-Host "Using $SelectedSource Python $SelectedVersion at $($SelectedPython.Path)"

if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Write-Host "Creating a project-local virtual environment with Python $SelectedVersion..."
    & $SelectedPython.Path -m venv (Join-Path $ProjectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the virtual environment." }
} elseif ($PythonPath) {
    $ExistingPython = Find-Python -ExplicitPath $VenvPython
    $ExistingVersion = "$($ExistingPython.Major).$($ExistingPython.Minor)"
    if ($ExistingVersion -ne $SelectedVersion) {
        throw ".venv uses Python $ExistingVersion but -PythonPath selected $SelectedVersion. Preserve the existing environment and choose a matching interpreter, or move .venv yourself before retrying."
    }
}

Write-Host "Installing Python dependencies into .venv..."
& $VenvPython -m pip install --disable-pip-version-check --require-virtualenv -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed under Python $SelectedVersion. Review pip's output above for the failing package, wheel, or network cause. The system Python was not modified."
}

Write-Host "Checking installed dependency consistency..."
& $VenvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check found dependency conflicts in .venv. Review the package conflict details above." }

Write-Host "Checking required package imports..."
& $VenvPython -c 'import av, cv2, fastapi, mediapipe, numpy, uvicorn; print("MediaPipe " + mediapipe.__version__ + ", PyAV " + av.__version__ + ", OpenCV " + cv2.__version__ + ", NumPy " + numpy.__version__)'
if ($LASTEXITCODE -ne 0) { throw "A required package failed to import in .venv. Review the import error above." }

Write-Host "Downloading and verifying vision models..."
& $VenvPython (Join-Path $ProjectRoot "scripts\download_models.py")
if ($LASTEXITCODE -ne 0) { throw "Model download failed. Restore network access and run setup.ps1 again." }

foreach ($Model in @("gesture_recognizer.task", "pose_landmarker_lite.task")) {
    $ModelPath = Join-Path $ProjectRoot "models\$Model"
    if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
        throw "Model verification failed: missing $Model after download."
    }
}

Write-Host "Setup complete. Run .\run.ps1 to start the website."
