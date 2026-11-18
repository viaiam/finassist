# 在任意目录调用此脚本；每个服务在当前终端前台运行，Ctrl+C 停止。
param(
    [ValidateSet('server', 'business', 'web')]
    [string]$Service = 'server'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    switch ($Service) {
        'server' { uv run --locked python -m finassist.main }
        'business' {
            Set-Location (Join-Path $projectRoot 'finassist-business')
            uv run --locked uvicorn app.app:app --env-file .env --host 127.0.0.1 --port 18081
        }
        'web' {
            Set-Location (Join-Path $projectRoot 'finassist-web')
            npm run dev
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "服务启动失败，退出码：$LASTEXITCODE" }
} finally {
    Pop-Location
}
