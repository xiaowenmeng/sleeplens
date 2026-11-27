$ErrorActionPreference = 'Stop'
$previewStatePath = Join-Path $PSScriptRoot '.state\public-preview-access.json'
if (-not (Test-Path -LiteralPath $previewStatePath)) {
    Write-Output 'No public preview is recorded.'
    exit 0
}
$previewState = Get-Content -LiteralPath $previewStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($previewKind in @('tunnel', 'app')) {
    $previewProcessId = $previewState.($previewKind + '_pid')
    if (-not $previewProcessId) { continue }
    $previewProcess = Get-Process -Id $previewProcessId -ErrorAction SilentlyContinue
    if (-not $previewProcess) { continue }
    $expectedStart = $previewState.($previewKind + '_started_at')
    $expectedExecutable = $previewState.($previewKind + '_executable')
    if (-not $expectedStart -or -not $expectedExecutable -or
        $previewProcess.StartTime.ToUniversalTime().ToString('o') -ne $expectedStart -or
        $previewProcess.Path -ne $expectedExecutable) {
        throw "Process identity changed; refusing to stop PID $previewProcessId."
    }
    & "$env:SystemRoot\System32\taskkill.exe" /PID $previewProcessId /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not stop the preview $previewKind process." }
}
Write-Output 'Public preview stopped.'
