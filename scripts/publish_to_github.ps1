# Create GitHub repo (main) and push — requires one-time gh auth
$ErrorActionPreference = "Stop"
$env:PATH = "C:\Program Files\Git\cmd;C:\Program Files\GitHub CLI;" + $env:PATH
Set-Location (Split-Path $PSScriptRoot -Parent)

function Wait-GhAuth {
    param([int]$Seconds = 120)
    for ($i = 1; $i -le ($Seconds / 5); $i++) {
        gh auth status 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
        Start-Sleep -Seconds 5
    }
    return $false
}

gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "GitHub login required. A browser/device window will open..." -ForegroundColor Yellow
    Start-Process "gh" -ArgumentList "auth","login","-h","github.com","-p","https","-w"
    if (-not (Wait-GhAuth)) {
        Write-Host "Login timed out. Run: gh auth login -h github.com -p https -w" -ForegroundColor Red
        exit 1
    }
}

$owner = "pirakill"
$repo = "pharma-connect"
Write-Host "Publishing https://github.com/$owner/$repo (main)..."

gh repo view "$owner/$repo" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    gh repo create $repo --public `
        --description "Infivita PharmaConnect — distributor consignment pharma ERP" `
        --source=. --remote=origin --push
} else {
    git push -u origin main
}

Write-Host "Done. CI: https://github.com/$owner/$repo/actions" -ForegroundColor Green