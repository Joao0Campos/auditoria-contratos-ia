# Executa a auditoria lendo a chave do Gemini do ambiente (nunca fixa no script).
# Ordem de busca: 1) variavel de ambiente GEMINI_API_KEY ja definida; 2) arquivo .env na pasta do projeto.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $env:GEMINI_API_KEY) {
    $envFile = Join-Path $PSScriptRoot ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            $linha = $_.Trim()
            if ($linha -and -not $linha.StartsWith("#") -and $linha.Contains("=")) {
                $nome, $valor = $linha.Split("=", 2)
                $nome = $nome.Trim()
                $valor = $valor.Trim().Trim('"').Trim("'")
                if ($valor -and -not (Test-Path "env:$nome")) {
                    Set-Item -Path "env:$nome" -Value $valor
                }
            }
        }
    }
}

if (-not $env:GEMINI_API_KEY) {
    Write-Host "[ERRO] GEMINI_API_KEY nao definida. Defina a variavel de ambiente ou copie .env.example para .env e preencha a chave." -ForegroundColor Red
    exit 1
}

python (Join-Path $PSScriptRoot "main.py")
