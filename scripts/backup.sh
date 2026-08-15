# Backup automation script for FlowSense (PowerShell)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Get timestamp
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = Join-Path "../backup" "flowbackup_$timestamp"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

Write-Host "Creating backup at $backupDir..."

# Items to backup (files/directories relative to script directory)
$itemsToBackup = @(
    ".env",
    "scripts",
    "requirements.txt",
    "requirements-dev-test.txt",
    "README.md"
)

foreach ($item in $itemsToBackup) {
    $sourcePath = Join-Path $scriptDir $item
    if (Test-Path $sourcePath) {
        Write-Host "Backing up $item ..."
        # Use robocopy to mirror (Windows)
        robocopy $sourcePath "$backupDir\$item" /MIR /NFL /NDL /NJH /NJS /NC /NS > $null
    } else {
        Write-Warning "Warning: $item not found, skipping."
    }
}

Write-Host "Backup completed. Location: $backupDir"