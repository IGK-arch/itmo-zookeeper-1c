param(
    [ValidateSet('setup','start','stop','roles','quorum','unsafe','fenced','verify','test','console','report')]
    [string]$Action='roles'
)
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$labPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $labPython)) {
    throw 'Создайте окружение: py -3.12 -m venv .venv'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    switch ($Action) {
        'setup' {
            & $labPython -m pip install --target python-packages -r requirements.txt
            if ($LASTEXITCODE) { throw 'pip failed' }
            & $labPython scripts/setup_runtime.py
        }
        'start' { & $labPython scripts/ensemble.py start }
        'stop' { & $labPython scripts/ensemble.py stop }
        'roles' { & $labPython scripts/ensemble.py roles }
        'quorum' { & $labPython scripts/test_ensemble.py 2>&1 | Tee-Object -FilePath evidence/ensemble-commands.txt }
        'unsafe' { & $labPython scripts/run_failover.py --fencing 0 2>&1 | Tee-Object -FilePath evidence/failover-unsafe-commands.txt }
        'fenced' { & $labPython scripts/run_failover.py --fencing 1 2>&1 | Tee-Object -FilePath evidence/failover-fenced-commands.txt }
        'verify' { & $labPython scripts/verify_results.py 2>&1 | Tee-Object -FilePath evidence/verification-commands.txt }
        'test' { & $labPython tests/test_fencing.py }
        'console' { & $labPython scripts/evidence_console.py }
        'report' { & $labPython scripts/build_report.py }
    }
    if ($LASTEXITCODE) { throw "Command failed: $LASTEXITCODE" }
} finally { Pop-Location }
