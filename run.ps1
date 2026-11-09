$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Run .\setup.ps1 first."
}

$RequiredModels = @(
    "gesture_recognizer.task",
    "pose_landmarker_lite.task"
)
foreach ($Model in $RequiredModels) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot "models\$Model"))) {
        throw "Missing model $Model. Run .\setup.ps1 first."
    }
}

$Port = 8000
while (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    $Port++
}

Write-Host "Website: http://127.0.0.1:$Port"
Write-Host "Press Ctrl+C to stop the server."
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port --no-access-log
