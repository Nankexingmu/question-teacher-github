$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw '未找到 Python 3。请先安装 Python，或在终端用完整 Python 路径运行 webapp/server.py。' }
& $python (Join-Path $PSScriptRoot 'server.py')
