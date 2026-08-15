# Token rotation script for Wendy API (PowerShell)

# Load environment variables from .env
$envPath = Join-Path -Path (Split-Path -Parent $MyInvocation.MyCommand.Path) -ChildPath '.env'
if (-Not (Test-Path $envPath)) {
    Write-Error "Error: .env file not found at $envPath"
    exit 1
}
# Dot-source the .env file to load variables
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*([^=]+?)\s*=\s*(.*)$') {
        $name = $Matches[1].Trim()
        $value = $Matches[2].Trim()
        # Remove surrounding quotes if present
        if ($value -match '^"(.*)"$') { $value = $Matches[1] }
        if ($value -match '^'(.*)'$') { $value = $Matches[1] }
        Set-Item -Path "Env:$name" -Value $value
    }
}

# Wendy token endpoint (assumes it returns JSON with token field)
$tokenEndpoint = "$Env:WENDY_API_URL/token"
Write-Host "Requesting new token from $tokenEndpoint..."
try {
    $response = Invoke-RestMethod -Method Post -Uri $tokenEndpoint -Headers @{ Authorization = "Bearer $Env:FLOWSENSE_API_KEY"; "Content-Type" = "application/json" } -ErrorAction Stop
} catch {
    Write-Error "Failed to obtain new token: $_"
    exit 1
}

# Extract token from response (adjust based on actual API structure)
$newToken = $response.token
if (-Not $newToken) {
    Write-Error "Token field not found in response. Response: $response"
    exit 1
}
Write-Host "New token acquired: $newToken"

# Update .env with new token
(Get-Content $envPath) | ForEach-Object {
    if ($_ -match '^\s*FLOWSENSE_API_KEY\s*=') {
        "FLOWSENSE_API_KEY=$newToken"
    } else {
        $_
    }
} | Set-Content -Path $envPath

Write-Host "Token rotation completed successfully."