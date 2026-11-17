param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogPath = Join-Path $ProjectRoot "setup.log"
try {
    Start-Transcript -Path $LogPath -Append -Force | Out-Null
} catch {
    Write-Warning "Could not start setup transcript: $($_.Exception.Message)"
}

trap {
    $Failure = $_
    Write-Host ""
    Write-Host "SETUP FAILED: $($Failure.Exception.Message)" -ForegroundColor Red
    Write-Host "Detailed error:" -ForegroundColor Yellow
    Write-Host ($Failure | Format-List * -Force | Out-String)
    Write-Host "Setup log: $LogPath" -ForegroundColor Yellow
    try { Stop-Transcript | Out-Null } catch {}
    break
}

function Get-PythonIdentity {
    param([string]$Executable)

    # Avoid embedded quotes in the native -c argument. Windows PowerShell's
    # legacy native-argument quoting can strip them before Python receives it.
    # A delimiter-based response is sufficient and keeps the probe quote-free.
    $ProbeCode = 'import struct,sys; print(chr(124).join((sys.executable,str(sys.version_info.major),str(sys.version_info.minor),str(struct.calcsize(chr(80))*8),sys.implementation.name)))'
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $Probe = & $Executable -c $ProbeCode 2>&1
        $ProbeExitCode = $LASTEXITCODE
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    if ($ProbeExitCode -ne 0 -or -not $Probe) {
        return $null
    }

    $ProbeText = ($Probe | Out-String).Trim()
    $Parts = $ProbeText -split '\|', 5
    if ($Parts.Count -ne 5) {
        return $null
    }

    try {
        return [pscustomobject]@{
            path = [string]$Parts[0]
            major = [int]$Parts[1]
            minor = [int]$Parts[2]
            bits = [int]$Parts[3]
            implementation = [string]$Parts[4]
        }
    } catch {
        return $null
    }
}

function Invoke-NativeCommand {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Step
    )

    Write-Host ""
    Write-Host ">>> $Step" -ForegroundColor Cyan
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        # Native programs may write diagnostics to stderr even when they
        # return useful output. Do not let PowerShell abort before we inspect
        # the process exit code and print the real diagnostic.
        $ErrorActionPreference = 'Continue'
        $Output = & $Executable @Arguments 2>&1
        $ExitCode = $LASTEXITCODE
        foreach ($Line in $Output) {
            if ($Line -is [System.Management.Automation.ErrorRecord]) {
                Write-Host $Line.ToString() -ForegroundColor Red
            } else {
                Write-Host ([string]$Line)
            }
        }
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }

    if ($ExitCode -ne 0) {
        throw "$Step failed with exit code $ExitCode. See $LogPath for the complete output."
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
    Invoke-NativeCommand -Executable $SelectedPython.Path -Arguments @("-m", "venv", (Join-Path $ProjectRoot ".venv")) -Step "Create .venv virtual environment"
} elseif ($PythonPath) {
    $ExistingPython = Find-Python -ExplicitPath $VenvPython
    $ExistingVersion = "$($ExistingPython.Major).$($ExistingPython.Minor)"
    if ($ExistingVersion -ne $SelectedVersion) {
        throw ".venv uses Python $ExistingVersion but -PythonPath selected $SelectedVersion. Preserve the existing environment and choose a matching interpreter, or move .venv yourself before retrying."
    }
}

Write-Host "Installing Python dependencies into .venv..."
Invoke-NativeCommand -Executable $VenvPython -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "--require-virtualenv", "-r", (Join-Path $ProjectRoot "requirements.txt")) -Step "Install requirements.txt dependencies"

Write-Host "Checking installed dependency consistency..."
Invoke-NativeCommand -Executable $VenvPython -Arguments @("-m", "pip", "check") -Step "Check dependency consistency"

Write-Host "Checking required package imports..."
$ImportCheck = 'import av, cv2, fastapi, mediapipe, numpy, uvicorn; print("MediaPipe " + mediapipe.__version__ + ", PyAV " + av.__version__ + ", OpenCV " + cv2.__version__ + ", NumPy " + numpy.__version__)'
Invoke-NativeCommand -Executable $VenvPython -Arguments @("-c", $ImportCheck) -Step "Verify required package imports"

Write-Host "Downloading and verifying vision models..."
Invoke-NativeCommand -Executable $VenvPython -Arguments @((Join-Path $ProjectRoot "scripts\download_models.py")) -Step "Download and verify vision models"

foreach ($Model in @("gesture_recognizer.task", "pose_landmarker_lite.task")) {
    $ModelPath = Join-Path $ProjectRoot "models\$Model"
    if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
        throw "Model verification failed: missing $Model after download."
    }
}

Write-Host ""
Write-Host "SETUP COMPLETE. Dependencies and model files were verified." -ForegroundColor Green
Write-Host "Run .\run.ps1 to start the website."
Write-Host "Setup log: $LogPath"
try { Stop-Transcript | Out-Null } catch {}
