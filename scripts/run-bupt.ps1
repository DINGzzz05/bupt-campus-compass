param(
    [switch]$Frontend,
    [switch]$Ollama,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

if ($Frontend) {
    Push-Location (Join-Path $repo 'frontend-vue')
    try {
        $env:VITE_API_URL = ''
        $env:VITE_WEB_RESEARCH_ENABLED = 'false'
        $env:VITE_HELPDESK_MODE_ENABLED = 'false'
        $env:VITE_ENABLE_MSW = 'false'
        $env:VITE_BUPT_RUNTIME = 'true'
        npm.cmd run dev
    } finally {
        Pop-Location
    }
    exit $LASTEXITCODE
}

Push-Location $repo
try {
    $python = Join-Path $repo '.venv/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $python)) {
        throw 'Create .venv and install requirements.txt before starting the backend.'
    }
    New-Item -ItemType Directory -Path '.bupt-local' -Force | Out-Null
    $env:APP_ENV = 'development'
    if (!$env:SQLALCHEMY_DATABASE_URI) {
        $env:SQLALCHEMY_DATABASE_URI = 'sqlite:///./.bupt-local/campus.sqlite3'
    }
    $env:FRONTEND_URL = 'http://127.0.0.1:5173'
    $env:AUTH_COOKIE_SECURE = 'false'
    if (!$env:SECRET_KEY) {
        $env:SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    }
    $env:RAG_FORCE_MOCK = 'false'
    $env:BUPT_RAG_ENABLED = 'true'
    $env:BUPT_OLLAMA_ENABLED = $Ollama.IsPresent.ToString().ToLowerInvariant()
    $env:HELPDESK_ENABLED = 'false'
    $env:HELPDESK_AGENT_ENABLED = 'false'
    $env:WEB_RESEARCH_ENABLED = 'false'
    $env:LOG_TO_FILE = 'false'
    $env:LOGGING_LEVEL = 'INFO'
    $env:LANGCHAIN_TRACING_V2 = 'false'
    $env:LANGSMITH_TRACING = 'false'
    & $python -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
exit $LASTEXITCODE
