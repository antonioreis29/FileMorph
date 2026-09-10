<#
.SYNOPSIS
    Gera o FileMorph.exe e o instalador de arquivo único.

.DESCRIPTION
    Dois passos, nesta ordem:

      1. PyInstaller empacota o aplicativo e o próprio Python em
         dist\FileMorph\. O resultado roda em máquinas sem Python.
      2. Inno Setup embrulha essa pasta num dist\installer\
         FileMorph-<versão>-setup.exe — um arquivo só, que pode ser
         enviado para outra pessoa.

    O segundo passo é opcional: sem o Inno Setup instalado, o script
    avisa e para depois do primeiro, que já é útil por si só.

    A versão vem de app/version.py e é repassada ao Inno Setup, para
    que não existam duas fontes discordando.

.EXAMPLE
    .\empacotar.ps1

    Faz os dois passos.

.EXAMPLE
    .\empacotar.ps1 -SomenteExe

    Só o executável, sem montar o instalador.
#>

[CmdletBinding()]
param(
    # Pular a montagem do instalador.
    [switch]$SomenteExe,

    # Reaproveitar o trabalho anterior do PyInstaller. Deixa a
    # compilação bem mais rápida, ao custo de eventualmente carregar
    # lixo de uma build antiga — por isso não é o padrão.
    [switch]$SemLimpar
)

$ErrorActionPreference = 'Stop'

$Raiz = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Raiz)) { $Raiz = (Get-Location).Path }

function Write-Passo { param([string]$m) Write-Host ''; Write-Host "  $m" -ForegroundColor Cyan }
function Write-Ok    { param([string]$m) Write-Host "      OK  $m" -ForegroundColor Green }
function Write-Warn  { param([string]$m) Write-Host "      !   $m" -ForegroundColor Yellow }
function Write-Info  { param([string]$m) Write-Host "      $m" -ForegroundColor DarkGray }

function Get-Versao {
    <#
        Lê a versão de app/version.py por expressão regular, como o
        install.ps1 faz. O formato esperado está documentado no próprio
        version.py.
    #>
    $arquivo = Join-Path $Raiz 'app\version.py'
    $conteudo = Get-Content -LiteralPath $arquivo -Raw
    if ($conteudo -match '__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"') {
        return $Matches[1]
    }
    throw "Nao consegui ler __version__ de '$arquivo'."
}

function Find-Python {
    <#
        Procura um Python que tenha o PyInstaller.

        A ordem não é arbitrária. O .venv do projeto vem primeiro
        porque é onde as versões exatas do requirements.txt estão. A
        instalação do FileMorph em %LOCALAPPDATA% vem logo depois: ela
        também tem um .venv completo, montado pelo install.ps1, e numa
        máquina de desenvolvimento costuma existir mesmo quando o
        projeto ainda não criou o seu.
    #>
    $candidatos = @(
        (Join-Path $Raiz '.venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\FileMorph\.venv\Scripts\python.exe')
    )

    foreach ($caminho in $candidatos) {
        if (Test-Path -LiteralPath $caminho) {
            $anterior = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            & $caminho -c 'import PyInstaller' 2>$null
            $codigo = $LASTEXITCODE
            $ErrorActionPreference = $anterior
            if ($codigo -eq 0) { return $caminho }
        }
    }

    # Último recurso: o Python do PATH.
    $doPath = Get-Command python -ErrorAction SilentlyContinue
    if ($doPath) {
        $anterior = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & $doPath.Source -c 'import PyInstaller' 2>$null
        $codigo = $LASTEXITCODE
        $ErrorActionPreference = $anterior
        if ($codigo -eq 0) { return $doPath.Source }
    }

    return $null
}

function Find-Inno {
    <#
        Procura o compilador do Inno Setup.

        O caminho em %LOCALAPPDATA%\Programs não é exótico: é onde o
        instalador cai quando é executado sem privilégio de
        administrador, que é o caso de um `winget install` comum. Uma
        busca que olhasse só em Program Files concluiria que a
        ferramenta não existe numa máquina onde ela está instalada e
        funcionando.
    #>
    $candidatos = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidatos) {
        if (Test-Path -LiteralPath $c) { return $c }
    }
    $doPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($doPath) { return $doPath.Source }
    return $null
}


Write-Host ''
Write-Host '  FileMorph - empacotamento' -ForegroundColor White
Write-Host '  -------------------------' -ForegroundColor DarkGray

try {
    $versao = Get-Versao
    Write-Info "Versao: $versao"

    # --- 1) Executavel ----------------------------------------------
    Write-Passo '[1/2] Empacotando o executavel (PyInstaller)'

    $python = Find-Python
    if (-not $python) {
        throw @"
Nenhum Python com o PyInstaller foi encontrado.

Para preparar um ambiente aqui no projeto:

    py -3 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt

O PyInstaller ja esta listado no requirements.txt.
"@
    }
    Write-Info "Python: $python"

    $argumentos = @('-m', 'PyInstaller', (Join-Path $Raiz 'FileMorph.spec'), '--noconfirm')
    if (-not $SemLimpar) {
        # --clean descarta o cache de analise. Sem isso, um arquivo
        # removido do projeto pode continuar entrando no pacote.
        $argumentos += '--clean'
    }

    Write-Info 'Isso costuma levar de um a tres minutos.'
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python @argumentos
    $codigo = $LASTEXITCODE
    $ErrorActionPreference = $anterior

    if ($codigo -ne 0) {
        throw "O PyInstaller falhou (codigo $codigo)."
    }

    $exe = Join-Path $Raiz "dist\FileMorph\FileMorph.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "O PyInstaller terminou sem erro mas o '$exe' nao apareceu."
    }

    $tamanho = [math]::Round(((Get-ChildItem (Join-Path $Raiz 'dist\FileMorph') -Recurse -File |
                               Measure-Object -Property Length -Sum).Sum / 1MB), 1)
    Write-Ok "dist\FileMorph\FileMorph.exe  ($tamanho MB na pasta)"

    # --- 2) Instalador ----------------------------------------------
    if ($SomenteExe) {
        Write-Passo '[2/2] Instalador ignorado por parametro'
        Write-Info 'O executavel esta pronto em dist\FileMorph\.'
    } else {
        Write-Passo '[2/2] Montando o instalador (Inno Setup)'

        $iscc = Find-Inno
        if (-not $iscc) {
            Write-Warn 'Inno Setup 6 nao encontrado - o instalador nao foi montado.'
            Write-Info ''
            Write-Info 'O executavel em dist\FileMorph\ ja funciona: a pasta inteira'
            Write-Info 'pode ser zipada e enviada, e roda em maquinas sem Python.'
            Write-Info 'O instalador apenas empacota isso num arquivo unico.'
            Write-Info ''
            Write-Info 'Para instalar o Inno Setup:'
            Write-Info '    winget install JRSoftware.InnoSetup'
            Write-Info '  ou baixe em https://jrsoftware.org/isdl.php'
            Write-Info ''
            Write-Info 'Depois rode este script de novo.'
        } else {
            Write-Info "ISCC: $iscc"

            $anterior = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            & $iscc "/DMyAppVersion=$versao" (Join-Path $Raiz 'installer\FileMorph.iss')
            $codigo = $LASTEXITCODE
            $ErrorActionPreference = $anterior

            if ($codigo -ne 0) {
                throw "O Inno Setup falhou (codigo $codigo)."
            }

            $setup = Join-Path $Raiz "dist\installer\FileMorph-$versao-setup.exe"
            if (Test-Path -LiteralPath $setup) {
                $mb = [math]::Round(((Get-Item $setup).Length / 1MB), 1)
                Write-Ok "$setup  ($mb MB)"
            } else {
                Write-Warn 'O Inno Setup terminou sem erro mas o setup.exe nao foi encontrado.'
            }
        }
    }

    Write-Host ''
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host '  Empacotamento concluido.' -ForegroundColor Green
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host ''
    exit 0

} catch {
    Write-Host ''
    Write-Host '  O empacotamento nao foi concluido.' -ForegroundColor Red
    Write-Host ''
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ''
    exit 1
}
