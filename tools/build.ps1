# Build the desktop-kanojo distributable folder via PyInstaller.
#
# Output: dist/desktop-kanojo/ — zip this and ship.
#
# Run:    powershell -ExecutionPolicy Bypass -File tools\build.ps1
#
# Notes:
# - Windows Defender often holds a read lock on freshly-built exes for a
#   few seconds. We retry the dist cleanup before launching PyInstaller.
# - PyInstaller puts data files under _internal/ by default; the project's
#   code uses cwd-relative paths (./live2d, ./personas, ./config.example.yaml),
#   so we promote those three out of _internal/ to the exe's top level after
#   the build finishes.

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$python = Join-Path $repo ".venv\Scripts\python.exe"
$pyi    = Join-Path $repo ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $python)) { Write-Error "venv not found: $python" }

if (-not (Test-Path $pyi)) {
    Write-Host "installing pyinstaller..." -ForegroundColor Cyan
    & $python -m pip install pyinstaller --quiet
}

$distRoot = Join-Path $repo "dist"
$outDir = Join-Path $distRoot "desktop-kanojo"

# Antivirus / search-indexer can hold file handles on a fresh build for a
# few seconds after it lands. Retry the cleanup so successive builds don't
# spuriously fail.
if (Test-Path $outDir) {
    Write-Host "cleaning previous build..." -ForegroundColor Cyan
    $ok = $false
    for ($i = 0; $i -lt 8; $i++) {
        try {
            Remove-Item -Recurse -Force $outDir
            $ok = $true
            break
        } catch {
            Start-Sleep -Seconds 3
        }
    }
    if (-not $ok) {
        Write-Error "could not remove $outDir — close any running desktop-kanojo.exe and retry."
    }
}

Write-Host "running pyinstaller..." -ForegroundColor Cyan
& $pyi "$repo\desktop-kanojo.spec" --clean --noconfirm
if ($LASTEXITCODE -ne 0) { Write-Error "pyinstaller failed" }

if (-not (Test-Path $outDir)) { Write-Error "build failed: $outDir not created" }

# Promote user-facing assets out of _internal/ to the exe's top level.
Write-Host ""
Write-Host "promoting user-facing assets to exe-level..." -ForegroundColor Cyan
$internal = Join-Path $outDir "_internal"
foreach ($item in "live2d", "personas", "config.example.yaml") {
    $src = Join-Path $internal $item
    $dst = Join-Path $outDir $item
    if (Test-Path $src) {
        if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
        Move-Item -Force $src $dst
        Write-Host "  $item"
    }
}

# Drop a tiny readme so unzippers see context.
$readmeContent = @'
desktop-kanojo
==============
首次启动：双击 desktop-kanojo.exe

第一次会弹两个对话框：
1. 缺 API key → 点"去注册页拿 key"，去智谱开放平台拿，粘贴到设置
2. 缺 Live2D 模型 → 点"打开下载页"，下个 sample zip，回来选 zip 装上

之后聊天 + 记忆 + 截屏感知都自动跑。运行时产生的文件：
  .env                    — 你填的 API keys
  config.yaml             — 自定义配置（可选，默认走 config.example.yaml）
  data/                   — SQLite 记忆库 + 偏好
  live2d/models/<name>/   — 你装的 Live2D 模型
  logs/                   — 日志

要重新走首启动向导，删掉 .env / data/preferences.yaml 再启动。

注意：解压到一个你自己可写的目录（桌面 / D 盘根目录 / 文档），
不要解压到 C:\Program Files\ — 那里写文件需要管理员权限。

源码与文档：https://github.com/lshhhhhhh/desktop-kanojo
'@
Set-Content -Path (Join-Path $outDir "首次启动看这里.txt") -Value $readmeContent -Encoding UTF8

$size = (Get-ChildItem $outDir -Recurse | Measure-Object -Property Length -Sum).Sum
Write-Host ""
Write-Host "build OK: $outDir" -ForegroundColor Green
Write-Host ("  size: {0:N1} MB ({1:N1} GB uncompressed)" -f ($size / 1MB), ($size / 1GB)) -ForegroundColor Green
Write-Host ""
Write-Host "to test:   cd `"$outDir`"; .\desktop-kanojo.exe" -ForegroundColor Cyan
Write-Host "to ship:   Compress-Archive -Path `"$outDir`" -DestinationPath dist\desktop-kanojo-win64.zip" -ForegroundColor Cyan
