# Multi-camera startup script for FlowSense (PowerShell)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Load environment config
$envPath = Join-Path $scriptDir '.env'
if (-Not (Test-Path $envPath)) {
    Write-Error "Error: .env file not found!"
    exit 1
}
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*([^=]+?)\s*=\s*(.*)$') {
        $name = $Matches[1].Trim()
        $value = $Matches[2].Trim()
        if ($value -match '^"(.*)"$') { $value = $Matches[1] }
        if ($value -match '^'(.*)'$') { $value = $Matches[1] }
        Set-Item -Path "Env:$name" -Value $value
    }
}

# List of camera IDs to start (can be extended or read from config)
$cameraIds = @(1,2,3,4,5)

Write-Host "Starting camera streams..."

$processes = @()
foreach ($id in $cameraIds) {
    Write-Host "Launching CCTV ID $id ..."
    # Build arguments for capture_frames.py
    $args = @("--id", $id, "--api-url", $Env:FLOWSENSE_API_URL, "--timeout", $Env:FLOWSENSE_API_TIMEOUT)
    # Start Python script in background
    $proc = Start-Process -FilePath python -ArgumentList $args -PassThru -WindowStyle Hidden
    $processes += $proc
}

# Wait for all processes to complete (optional)
# Wait-Process -InputObject $processes

Write-Host "All camera streams started."