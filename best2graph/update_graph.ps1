$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Get-DotEnvValue([string]$Name) {
    $line = Get-Content -Encoding UTF8 -LiteralPath ".\.env" |
        Where-Object { $_ -match "^\s*$Name\s*=" } |
        Select-Object -First 1
    if (-not $line) {
        return ""
    }
    return (($line -replace "^\s*$Name\s*=\s*", "").Trim().Trim('"').Trim("'"))
}

$openRouterKey = Get-DotEnvValue "OPENROUTER_API_KEY"
$openRouterBase = Get-DotEnvValue "OPENROUTER_BASE_URL"
$model = Get-DotEnvValue "OPENAI_MODEL"

if (-not $openRouterKey) {
    throw "OPENROUTER_API_KEY not found in .env"
}
if (-not $openRouterBase) {
    $openRouterBase = "https://openrouter.ai/api/v1"
}
if (-not $model) {
    $model = "anthropic/claude-sonnet-4"
}

# Graphify's OpenAI backend defaults to api.openai.com. The project uses
# OpenRouter, so keep this venv-local patch idempotent and out of production code.
$llmPath = ".\best2graph\.venv\Lib\site-packages\graphify\llm.py"
$llmText = Get-Content -Raw -Encoding UTF8 -LiteralPath $llmPath
if ($llmText -notmatch 'OPENAI_BASE_URL') {
    $llmText = $llmText.Replace(
        '"base_url": "https://api.openai.com/v1",',
        '"base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),'
    )
    Set-Content -Encoding UTF8 -LiteralPath $llmPath -Value $llmText
}

$env:OPENAI_API_KEY = $openRouterKey
$env:OPENAI_BASE_URL = $openRouterBase
$env:NO_PROXY = "*"
$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:ALL_PROXY = ""

.\best2graph\.venv\Scripts\graphify.exe extract . `
    --backend openai `
    --model $model `
    --out .\best2graph `
    --no-cluster `
    --exclude best2graph/ `
    --exclude best2obs/ `
    --exclude .env `
    --exclude logs/ `
    --exclude *.log `
    --exclude .venv/ `
    --exclude __pycache__/

.\best2graph\.venv\Scripts\graphify.exe cluster-only .\best2graph `
    --graph .\best2graph\graphify-out\graph.json `
    --no-label

.\best2graph\.venv\Scripts\graphify.exe tree `
    --graph .\best2graph\graphify-out\graph.json `
    --output .\best2graph\graphify-out\GRAPH_TREE.html `
    --root . `
    --label best2
