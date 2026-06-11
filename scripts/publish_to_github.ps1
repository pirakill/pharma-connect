# Create GitHub repo (main) and push — run once after: gh auth login
$ErrorActionPreference = "Stop"
$env:PATH = "C:\Program Files\Git\cmd;C:\Program Files\GitHub CLI;" + $env:PATH

Set-Location (Split-Path $PSScriptRoot -Parent)

gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in. Run: gh auth login" -ForegroundColor Yellow
    gh auth login -h github.com -p https -w
}

$repo = "pirakill/pharma-connect"
Write-Host "Creating $repo and pushing main..."
gh repo create pharma-connect --public --source=. --remote=origin --push 2>$null
if ($LASTEXITCODE -ne 0) {
    git remote remove origin 2>$null
    git remote add origin "https://github.com/$repo.git"
    git push -u origin main
}

Write-Host "Done. CI: https://github.com/$repo/actions" -ForegroundColor Green