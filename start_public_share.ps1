param([ValidateRange(1024, 65535)][int]$Port = 8503)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$previewRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$previewDirectory = Join-Path $previewRoot '.state'
$previewStatePath = Join-Path $previewDirectory 'public-preview-access.json'
$previewPython = Join-Path $previewRoot '.venv\Scripts\python.exe'
$previewTunnel = Join-Path $previewDirectory 'cloudflared.exe'
$previewWorkingDirectory = $previewRoot
$previewEntry = 'app.py'
if (-not (Test-Path -LiteralPath $previewPython) -or -not (Test-Path -LiteralPath $previewTunnel)) {
    throw 'The local Python environment and .state/cloudflared.exe are required.'
}
New-Item -ItemType Directory -Path $previewDirectory -Force | Out-Null
if (Test-Path -LiteralPath $previewStatePath) {
    $previousPreview = Get-Content -LiteralPath $previewStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $previousTunnel = Get-Process -Id $previousPreview.tunnel_pid -ErrorAction SilentlyContinue
    if ($previousTunnel -and $previousPreview.tunnel_started_at -and $previousPreview.tunnel_executable -and
        $previousTunnel.StartTime.ToUniversalTime().ToString('o') -eq $previousPreview.tunnel_started_at -and
        $previousTunnel.Path -eq $previousPreview.tunnel_executable) {
        throw 'A recorded public tunnel is still running. Run stop_public_share.ps1 before starting a new preview.'
    }
}
$previewListener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
try { $previewListener.Start() } finally { $previewListener.Stop() }
$previewBytes = New-Object byte[] 18
$previewRandom = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $previewRandom.GetBytes($previewBytes) } finally { $previewRandom.Dispose() }
$previewPassword = [Convert]::ToBase64String($previewBytes).Replace('+', '-').Replace('/', '_')
$previousMode = $env:SLEEPLENS_SHARE_MODE
$previousPassword = $env:SLEEPLENS_SHARE_PASSWORD
$previewDiscardProxies = @{}
foreach ($previewProxyName in @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')) {
    $previewProxyValue = [Environment]::GetEnvironmentVariable($previewProxyName, 'Process')
    if ($previewProxyValue) {
        $previewProxyUri = $null
        if ([Uri]::TryCreate($previewProxyValue, [UriKind]::Absolute, [ref]$previewProxyUri) -and
            $previewProxyUri.Host -in @('127.0.0.1', 'localhost', '::1', '[::1]') -and
            $previewProxyUri.Port -eq 9) {
            $previewDiscardProxies[$previewProxyName] = $previewProxyValue
        }
    }
}
$previewAppProcess = $null
$previewTunnelProcess = $null
$previewAppOut = Join-Path $previewDirectory 'public-app.out.log'
$previewAppErr = Join-Path $previewDirectory 'public-app.err.log'
$previewTunnelOut = Join-Path $previewDirectory 'public-tunnel.out.log'
$previewTunnelErr = Join-Path $previewDirectory 'public-tunnel.err.log'
try {
    # Tool runners can inject a loopback discard proxy. Do not pass it to the app.
    # Other user-configured proxy addresses remain intact.
    foreach ($previewProxyName in $previewDiscardProxies.Keys) {
        [Environment]::SetEnvironmentVariable($previewProxyName, $null, 'Process')
    }
    $env:SLEEPLENS_SHARE_MODE = '1'
    $env:SLEEPLENS_SHARE_PASSWORD = $previewPassword
    $previewAppProcess = Start-Process -FilePath $previewPython -ArgumentList @(
        '-m', 'streamlit', 'run', $previewEntry, '--server.address', '127.0.0.1',
        '--server.port', $Port, '--server.headless', 'true'
    ) -WorkingDirectory $previewWorkingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput $previewAppOut -RedirectStandardError $previewAppErr
    $previewAppReady = $false
    $previewDeadline = [DateTime]::UtcNow.AddSeconds(25)
    while ([DateTime]::UtcNow -lt $previewDeadline) {
        $previewAppProcess.Refresh()
        if ($previewAppProcess.HasExited) { throw 'The preview app exited. Inspect .state/public-app.err.log.' }
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/_stcore/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $previewAppReady = $true; break }
        } catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $previewAppReady) { throw 'The local preview did not become ready within 25 seconds.' }
    $previewTunnelProcess = Start-Process -FilePath $previewTunnel -ArgumentList @(
        '--no-autoupdate', 'tunnel', '--url', "http://127.0.0.1:$Port", '--protocol', 'http2'
    ) -WorkingDirectory $previewRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $previewTunnelOut -RedirectStandardError $previewTunnelErr
    $previewUrl = $null
    $previewDeadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $previewDeadline) {
        $previewTunnelProcess.Refresh()
        if ($previewTunnelProcess.HasExited) { throw 'The public tunnel exited. Inspect .state/public-tunnel.err.log.' }
        $previewLog = Get-Content -LiteralPath $previewTunnelErr -Raw -ErrorAction SilentlyContinue
        if ($previewLog) {
            $previewUrlMatch = [regex]::Match($previewLog, 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($previewUrlMatch.Success) { $previewUrl = $previewUrlMatch.Value; break }
        }
        Start-Sleep -Milliseconds 300
    }
    if (-not $previewUrl) { throw 'The tunnel did not return a public URL within 30 seconds.' }
    $previewAppProcess.Refresh()
    $previewTunnelProcess.Refresh()
    $previewState = [ordered]@{
        port = $Port
        password = $previewPassword
        app_pid = $previewAppProcess.Id
        tunnel_pid = $previewTunnelProcess.Id
        url = $previewUrl
        created_at = [DateTime]::UtcNow.ToString('o')
        app_started_at = $previewAppProcess.StartTime.ToUniversalTime().ToString('o')
        app_executable = $previewAppProcess.Path
        tunnel_started_at = $previewTunnelProcess.StartTime.ToUniversalTime().ToString('o')
        tunnel_executable = $previewTunnelProcess.Path
        app_version = 'working-project'
        app_directory = $previewWorkingDirectory
    }
    $previewState | ConvertTo-Json | Set-Content -LiteralPath $previewStatePath -Encoding UTF8
    Write-Output "URL: $previewUrl"
    Write-Output "PASSWORD: $previewPassword"
    Write-Output 'Keep this computer awake and connected. Run stop_public_share.ps1 to stop sharing.'
} catch {
    foreach ($previewProcess in @($previewTunnelProcess, $previewAppProcess)) {
        if ($previewProcess) {
            $previewProcess.Refresh()
            if (-not $previewProcess.HasExited) {
                & "$env:SystemRoot\System32\taskkill.exe" /PID $previewProcess.Id /T /F | Out-Null
            }
        }
    }
    throw
} finally {
    $env:SLEEPLENS_SHARE_MODE = $previousMode
    $env:SLEEPLENS_SHARE_PASSWORD = $previousPassword
    foreach ($previewProxyName in $previewDiscardProxies.Keys) {
        [Environment]::SetEnvironmentVariable($previewProxyName, $previewDiscardProxies[$previewProxyName], 'Process')
    }
}
