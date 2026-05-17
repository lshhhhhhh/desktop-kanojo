# Build the desktop-kanojo distributable folder via PyInstaller.
#
# Output: dist/desktop-kanojo/ -- zip this and ship.
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

# Don't set ErrorActionPreference = Stop globally: pyinstaller writes
# benign warnings to stderr, and Stop mode treats every native stderr line
# as a terminating error. We check $LASTEXITCODE manually instead.

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
        Write-Error "could not remove $outDir -- close any running desktop-kanojo.exe and retry."
    }
}

Write-Host "running pyinstaller..." -ForegroundColor Cyan
& $pyi "$repo\desktop-kanojo.spec" --clean --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Host "pyinstaller failed (exit $LASTEXITCODE) -- often Defender locking a previous build." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $outDir)) {
    Write-Host "build failed: $outDir not created" -ForegroundColor Red
    exit 1
}

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

# Trim Qt + Chromium assets we don't use. Saves ~130 MB.
# Documented per-line so it's clear what's gone if something later breaks.
Write-Host ""
Write-Host "pruning unused Qt/Chromium assets..." -ForegroundColor Cyan
$pyside = Join-Path $internal "PySide6"

# Whole directories
$pruneDirs = @(
    # QML runtime -- we use QtWidgets, no QML loaded anywhere.
    "qml",
    # 3D scenegraph -- unrelated to QtWebEngine.
    "Qt6Quick3D",
    "Qt6Quick3DRuntimeRender"
)
foreach ($d in $pruneDirs) {
    $p = Join-Path $pyside $d
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "  removed PySide6\$d"
    }
}

# Compute the transitive Qt6*.dll dependency closure starting from the
# modules we actually import (window.py uses QtWebEngineCore + Widgets,
# core/voice/playback uses QtMultimedia, etc). Anything Qt6*.dll under
# PySide6/ that's NOT in the closure is dead weight and gets pruned.
# This is a whitelist approach -- safer than maintaining a blacklist,
# since PyInstaller's collection changes between PySide6 versions.
function Get-QtDeps($dllPath) {
    if (-not (Test-Path $dllPath)) { return @() }
    $bytes = [System.IO.File]::ReadAllBytes($dllPath)
    $s = [System.Text.Encoding]::ASCII.GetString($bytes)
    [regex]::Matches($s, '[Qq]t6[A-Za-z0-9]+\.dll') |
        ForEach-Object { $_.Value } |
        Sort-Object -Unique
}

$queue = New-Object System.Collections.Queue
$keep = New-Object System.Collections.Generic.HashSet[string]
@(
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll',
    'Qt6WebEngineCore.dll', 'Qt6WebEngineWidgets.dll',
    'Qt6Multimedia.dll', 'Qt6Network.dll'
) | ForEach-Object {
    $null = $keep.Add($_); $queue.Enqueue($_)
}
while ($queue.Count -gt 0) {
    $d = $queue.Dequeue()
    Get-QtDeps (Join-Path $pyside $d) | ForEach-Object {
        if (-not $keep.Contains($_)) {
            $null = $keep.Add($_); $queue.Enqueue($_)
        }
    }
}

$prunedCount = 0
Get-ChildItem $pyside -Filter 'Qt6*.dll' -File | ForEach-Object {
    if (-not $keep.Contains($_.Name)) {
        Remove-Item -Force $_.FullName
        $prunedCount++
    }
}
Write-Host "  pruned $prunedCount unused Qt6*.dll (kept $($keep.Count) in closure)"

# Software OpenGL fallback. Used only on bare-VM / no-driver setups; ~20 MB.
$swgl = Join-Path $pyside "opengl32sw.dll"
if (Test-Path $swgl) {
    Remove-Item -Force $swgl
    Write-Host "  removed PySide6\opengl32sw.dll (software GL fallback)"
}

# Qt translations (.qm) -- keep only English + Simplified Chinese; the UI
# itself is hardcoded Chinese, but a few Qt-built-in dialogs use these.
$trans = Join-Path $pyside "translations"
if (Test-Path $trans) {
    Get-ChildItem $trans -Filter "*.qm" | Where-Object {
        $_.Name -notmatch '_(en|zh_CN)\.qm$'
    } | Remove-Item -Force
    # Also drop locale subfolders that aren't en or zh-CN
    Get-ChildItem $trans -Directory | Where-Object {
        $_.Name -notmatch '^(en|zh-CN|qtwebengine_locales)$'
    } | Remove-Item -Recurse -Force
}

# Chromium UI locales -- Chromium ships its own per-language strings
# separate from Qt. Keep en-US and zh-CN only.
$chromeLocales = @(
    (Join-Path $pyside "translations\qtwebengine_locales"),
    (Join-Path $pyside "Qt6\translations\qtwebengine_locales"),
    (Join-Path $pyside "resources\qtwebengine_locales")
)
foreach ($loc in $chromeLocales) {
    if (Test-Path $loc) {
        Get-ChildItem $loc -File | Where-Object {
            $_.BaseName -notin @("en-US", "zh-CN")
        } | Remove-Item -Force
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
  .env                    -- 你填的 API keys
  config.yaml             -- 自定义配置（可选，默认走 config.example.yaml）
  data/                   -- SQLite 记忆库 + 偏好
  live2d/models/<name>/   -- 你装的 Live2D 模型
  logs/                   -- 日志

要重新走首启动向导，删掉 .env / data/preferences.yaml 再启动。

注意：解压到一个你自己可写的目录（桌面 / D 盘根目录 / 文档），
不要解压到 C:\Program Files\ -- 那里写文件需要管理员权限。

源码与文档：https://github.com/lshhhhhhh/desktop-kanojo
'@
Set-Content -Path (Join-Path $outDir "首次启动看这里.txt") -Value $readmeContent -Encoding UTF8

$size = (Get-ChildItem $outDir -Recurse | Measure-Object -Property Length -Sum).Sum
Write-Host ""
Write-Host "build OK: $outDir" -ForegroundColor Green
Write-Host ("  unpacked size: {0:N1} MB" -f ($size / 1MB)) -ForegroundColor Green

# Pack a zip ready for distribution. Compress-Archive is slow on 600+ MB
# but pure-PowerShell (no 7zip dep). Skippable via -SkipZip if you only
# want the folder.
$zipPath = Join-Path $distRoot "desktop-kanojo-win64.zip"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Write-Host ""
Write-Host "compressing to zip..." -ForegroundColor Cyan
Compress-Archive -Path $outDir -DestinationPath $zipPath -CompressionLevel Optimal
$zipSize = (Get-Item $zipPath).Length
Write-Host ("  zip: $zipPath ({0:N1} MB)" -f ($zipSize / 1MB)) -ForegroundColor Green
Write-Host ""
Write-Host "to test:   cd `"$outDir`"; .\desktop-kanojo.exe" -ForegroundColor Cyan
Write-Host "to ship:   upload $zipPath as a GitHub release asset" -ForegroundColor Cyan
