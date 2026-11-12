param(
    [ValidateSet('Start', 'Advance', 'Status', 'Demo')][string]$Mode = 'Start',
    [string]$Run = '',
    [string]$Proposal = '',
    [ValidateSet('parallel22', 'trinomial22')][string]$Family = 'trinomial22',
    [ValidateRange(1, 20)][int]$Rounds = 3,
    [ValidateRange(0, 2147483647)][int]$Seed = 22,
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$pythonArgs = @()
if (-not $Python) {
    $localPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    $workspacePython = Join-Path $PSScriptRoot '../../.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $localPython) { $Python = $localPython }
    elseif (Test-Path -LiteralPath $workspacePython) { $Python = $workspacePython }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { $Python = 'py'; $pythonArgs = @('-3') }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = 'python' }
    else { throw 'Python 3.11+ is required. Pass -Python with its executable path.' }
}
if (-not $Run) {
    if ($Mode -in @('Advance', 'Status')) { throw '-Run is required for Advance and Status.' }
    $Run = 'runs/chat-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $Python @pythonArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
    $cycleArgs = @('-m', 'discovery')
    switch ($Mode) {
        'Start' { $cycleArgs += @('start', '--output', $Run, '--family', $Family, '--rounds', "$Rounds", '--seed', "$Seed") }
        'Advance' {
            if (-not $Proposal) { throw '-Proposal is required for Advance.' }
            $cycleArgs += @('advance', '--run', $Run, '--proposal', $Proposal)
        }
        'Status' { $cycleArgs += @('status', '--run', $Run) }
        'Demo' { $cycleArgs += @('demo', '--output', $Run) }
    }
    & $Python @pythonArgs @cycleArgs
    if ($LASTEXITCODE -ne 0) { throw 'Cycle step failed. Saved run files were retained.' }
    Write-Host "Run: $Run"
    if ($Mode -eq 'Start') {
        Write-Host 'The existing Codex chat should read next_prompt, propose targets and run Advance.'
        Write-Host 'See docs/LLM_SEARCH.md. No API connection is used.'
    }
}
finally { Pop-Location }
