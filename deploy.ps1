# Soccer Under Strategy — push to GitHub then deploy on Render (free HTTPS hosting)
param(
  [string]$GitHubUser = "",
  [string]$RepoName = "soccer-under-strategy"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".git")) {
  git init
  git branch -M main
}

git add -A
git diff --cached --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
  git commit -m "Soccer Under Strategy: live 1H/2H under-goals app ready for deploy"
}

if (-not $GitHubUser) {
  Write-Host ""
  Write-Host "=== Soccer Under Strategy deploy ===" -ForegroundColor Cyan
  Write-Host "1. Create a new repo at https://github.com/new (name: soccer-under-strategy, private or public)"
  Write-Host "2. Run this script with your GitHub username:"
  Write-Host "   .\deploy.ps1 -GitHubUser YOUR_USERNAME"
  Write-Host ""
  Write-Host "3. Then open https://dashboard.render.com/select-repo?type=blueprint"
  Write-Host "   Connect the repo — Render reads render.yaml automatically."
  exit 0
}

$remote = "https://github.com/$GitHubUser/$RepoName.git"
$existing = git remote get-url origin 2>$null
if (-not $existing) {
  git remote add origin $remote
} else {
  git remote set-url origin $remote
}

Write-Host "Pushing to $remote ..."
git push -u origin main

Write-Host ""
Write-Host "Open https://dashboard.render.com/blueprints and connect $GitHubUser/$RepoName" -ForegroundColor Green
Write-Host "Render will build from render.yaml and give you a public HTTPS URL."