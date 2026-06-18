# Pro Punter — background watcher: auto-commit and push on file changes
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$pollSeconds = 5
$debounceSeconds = 8
$syncScript = Join-Path $PSScriptRoot "sync-github.ps1"

Write-Host "Pro Punter — GitHub auto-sync watching $PSScriptRoot" -ForegroundColor Cyan
Write-Host "Pushes ~${debounceSeconds}s after changes. Keep this window open. Ctrl+C to stop." -ForegroundColor DarkGray

function Test-HasChanges {
  git add -A 2>$null | Out-Null
  git diff --cached --quiet 2>$null
  return $LASTEXITCODE -ne 0
}

function Invoke-Sync {
  try {
    & $syncScript -Quiet
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Pushed to GitHub." -ForegroundColor Green
  } catch {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Sync failed: $_" -ForegroundColor Red
  }
}

$dirtySince = $null

while ($true) {
  if (Test-HasChanges) {
    if (-not $dirtySince) {
      $dirtySince = Get-Date
      Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Changes detected, waiting ${debounceSeconds}s..." -ForegroundColor DarkYellow
    } elseif (((Get-Date) - $dirtySince).TotalSeconds -ge $debounceSeconds) {
      Invoke-Sync
      $dirtySince = $null
    }
  } else {
    $dirtySince = $null
  }
  Start-Sleep -Seconds $pollSeconds
}