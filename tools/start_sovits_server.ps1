# Launch the GPT-SoVITS HTTP API server (api_v2.py) for desktop-kanojo's
# voice backend. The server listens at http://127.0.0.1:9880.
#
# Configure via env vars (or override with -Python / -Repo / -Config):
#   GPT_SOVITS_DIR     — path to a cloned GPT-SoVITS repo
#   GPT_SOVITS_PYTHON  — python.exe of a GPT-SoVITS-compatible env
#   GPT_SOVITS_CONFIG  — path (relative to repo) to your tts_infer YAML
#
# Run:
#   powershell -ExecutionPolicy Bypass -File tools\start_sovits_server.ps1

param(
    [string]$Python = $env:GPT_SOVITS_PYTHON,
    [string]$Repo   = $env:GPT_SOVITS_DIR,
    [string]$Config = $(if ($env:GPT_SOVITS_CONFIG) { $env:GPT_SOVITS_CONFIG } else { "GPT_SoVITS\configs\tts_infer.yaml" })
)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

if (-not $Repo)   { Write-Error "GPT_SOVITS_DIR not set. Set env var or pass -Repo." }
if (-not $Python) { Write-Error "GPT_SOVITS_PYTHON not set. Set env var or pass -Python." }
$env:PYTHONPATH = "$Repo;$Repo\GPT_SoVITS"

if (-not (Test-Path $Python))            { Write-Error "Python not found at $Python" }
if (-not (Test-Path "$Repo\api_v2.py"))  { Write-Error "GPT-SoVITS repo not found at $Repo" }
if (-not (Test-Path "$Repo\$Config"))    { Write-Error "TTS config not found: $Config" }

Write-Host "Starting GPT-SoVITS API server..." -ForegroundColor Cyan
Write-Host "  Python : $Python"
Write-Host "  Repo   : $Repo"
Write-Host "  Config : $Config"
Write-Host "  Address: http://127.0.0.1:9880"
Write-Host ""
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

Set-Location $Repo
& $Python api_v2.py -a 127.0.0.1 -p 9880 -c $Config
