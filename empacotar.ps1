<#
.SYNOPSIS
    Gera o instalador do FileMorph (e, opcionalmente, o executavel portatil).

.DESCRIPTION
    Etapas, nesta ordem. Qualquer etapa essencial que falhar encerra o
    script com codigo de saida 1.

      1. Confere o Python: 64 bits, 3.12 ou mais novo, com o PyInstaller.
      2. Roda os testes unitarios (pule com -PularTestes).
      3. PyInstaller empacota o aplicativo e o proprio Python em
         dist\FileMorph\. Essa pasta NAO e para ser enviada sozinha: o
         FileMorph.exe dela depende dos arquivos ao lado.
      4. Confere o pacote: o executavel existe, nada de desenvolvimento
         (testes, caches, .git) entrou, e o executavel passa na
         verificacao rapida (FileMorph.exe --smoke-test): converte uma
         imagem, monta um PDF e abre a janela principal, sem o Python da
         maquina.
      5. Inno Setup embrulha a pasta em dist\installer\
         FileMorph-<versao>-setup.exe — o arquivo a ser compartilhado.
      6. Calcula o SHA-256 do setup.exe (arquivo .sha256 ao lado) e apaga
         os setup.exe de versoes anteriores que estavam em dist\installer.
      7. Com -Portatil: gera dist\portable\FileMorph-<versao>-portable.exe
         (PyInstaller onefile), verifica e calcula o SHA-256 dele.

    A versao vem de app/version.py e e repassada ao Inno Setup, para que
    nao existam duas fontes discordando.

.EXAMPLE
    .\empacotar.ps1

    Testes, executavel, verificacao, instalador e hash.

.EXAMPLE
    .\empacotar.ps1 -Portatil

    O mesmo, mais o executavel portatil.

.EXAMPLE
    .\empacotar.ps1 -Python C:\Python313\python.exe -PularTestes
#>

[CmdletBinding()]
param(
    # Pular a montagem do instalador (so o executavel e a verificacao).
    [switch]$SomenteExe,

    # Gerar tambem o executavel portatil de arquivo unico.
    [switch]$Portatil,

    # Nao rodar os testes unitarios antes de empacotar.
    [switch]$PularTestes,

    # Reaproveitar o trabalho anterior do PyInstaller. Deixa a
    # compilacao bem mais rapida, ao custo de eventualmente carregar
    # lixo de uma build antiga — por isso nao e o padrao.
    [switch]$SemLimpar,

    # Python a usar. Sem isto, o script procura um com o PyInstaller.
    [string]$Python = ''
)

$ErrorActionPreference = 'Stop'

# A raiz e sempre a pasta deste script, e nunca o diretorio de trabalho:
# o PyInstaller apaga e recria dist\ e build\ dentro dela, e um caminho
# deduzido de onde o terminal estava poderia apontar para outro lugar.
$Raiz = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Raiz) -and $MyInvocation.MyCommand.Path) {
    $Raiz = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if ([string]::IsNullOrWhiteSpace($Raiz) -or
    -not (Test-Path -LiteralPath (Join-Path $Raiz 'FileMorph.spec')) -or
    -not (Test-Path -LiteralPath (Join-Path $Raiz 'app\version.py'))) {
    Write-Host '  Nao foi possivel identificar a pasta do projeto a partir deste script.' -ForegroundColor Red
    Write-Host '  Rode-o pelo caminho completo: powershell -File C:\...\FileMorph\empacotar.ps1' -ForegroundColor Red
    exit 1
}

$Dist = Join-Path $Raiz 'dist'
$Build = Join-Path $Raiz 'build'

function Write-Passo { param([string]$m) Write-Host ''; Write-Host "  $m" -ForegroundColor Cyan }
function Write-Ok    { param([string]$m) Write-Host "      OK  $m" -ForegroundColor Green }
function Write-Warn  { param([string]$m) Write-Host "      !   $m" -ForegroundColor Yellow }
function Write-Info  { param([string]$m) Write-Host "      $m" -ForegroundColor DarkGray }

function Get-Metadado {
    <#
        Le uma constante de app/version.py por expressao regular, como o
        FileMorph.spec faz. O formato esperado esta documentado no proprio
        version.py.
    #>
    param([Parameter(Mandatory)][string]$Nome, [string]$Padrao = '')
    $conteudo = Get-Content -LiteralPath (Join-Path $Raiz 'app\version.py') -Raw -Encoding UTF8
    if ($conteudo -match "(?m)^$Nome\s*=\s*`"([^`"]*)`"") {
        return $Matches[1]
    }
    return $Padrao
}

function Invoke-Externo {
    <#
        Executa um programa e devolve so o codigo de saida.

        Existe para que a danca do $ErrorActionPreference apareca uma
        vez so. Ela e necessaria porque o PowerShell 5.1 transforma
        cada linha que um executavel nativo escreve em stderr num
        ErrorRecord — com 'Stop' valendo, o pip escrevendo um aviso
        inofensivo abortaria o empacotamento inteiro.

        `Silencioso` descarta a saida, para as sondagens; sem ele a
        saida aparece na tela, que e o que se quer numa operacao
        demorada como o PyInstaller.

        **O `Out-Host` nao e decoracao.** Numa funcao do PowerShell,
        tudo que vai para a saida padrao compoe o valor de retorno — sem
        ele, quem chamasse esta funcao receberia as centenas de linhas
        que o PyInstaller imprime *mais* o codigo de saida, num array,
        e a comparacao `-ne 0` daria verdadeira mesmo num build que
        funcionou.
    #>
    param(
        [Parameter(Mandatory)][string]$Programa,
        [string[]]$Argumentos = @(),
        [switch]$Silencioso
    )

    $anterior = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Silencioso) {
            & $Programa @Argumentos 2>$null | Out-Null
        } else {
            & $Programa @Argumentos 2>&1 | ForEach-Object { "$_" } | Out-Host
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $anterior
    }
}

function Find-Python {
    <#
        Procura um Python que tenha o PyInstaller: o .venv do projeto
        primeiro (e onde as versoes de constraints-release.txt costumam
        estar), depois o do PATH.
    #>
    $candidatos = @((Join-Path $Raiz '.venv\Scripts\python.exe'))
    $doPath = Get-Command python -ErrorAction SilentlyContinue
    if ($doPath) { $candidatos += $doPath.Source }

    foreach ($caminho in $candidatos) {
        if (-not (Test-Path -LiteralPath $caminho)) { continue }
        if ((Invoke-Externo -Programa $caminho -Argumentos @('-c', 'import PyInstaller') -Silencioso) -eq 0) {
            return $caminho
        }
    }
    return $null
}

function Find-Inno {
    <#
        Procura o compilador do Inno Setup.

        O caminho em %LOCALAPPDATA%\Programs nao e exotico: e onde o
        instalador cai quando e executado sem privilegio de
        administrador, que e o caso de um `winget install` comum.
    #>
    $candidatos = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidatos) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    $doPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($doPath) { return $doPath.Source }
    return $null
}

function Test-PacoteLimpo {
    <#
        Falha se algo de desenvolvimento entrou no pacote. Os testes, as
        ferramentas e os caches ficam no repositorio; a maquina do usuario
        nao precisa de nenhum deles.
    #>
    param([Parameter(Mandatory)][string]$Pasta)

    $proibidos = Get-ChildItem -LiteralPath $Pasta -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.PSIsContainer -and $_.Name -in @('.git', '.pytest_cache', '__pycache__', 'tests', 'tools', '.venv')) -or
            (-not $_.PSIsContainer -and ($_.Name -like '*.pyc' -or $_.Name -like '*.filemorph-tmp*'))
        }
    if ($proibidos) {
        $lista = ($proibidos | Select-Object -First 10 | ForEach-Object { $_.FullName.Substring($Pasta.Length) }) -join "`n        "
        throw "O pacote tem arquivos de desenvolvimento:`n        $lista"
    }
}

function Invoke-SmokeTest {
    <#
        Roda o executavel com --smoke-test e confere o relatorio.

        As configuracoes e os logs vao para uma pasta temporaria
        (FILEMORPH_DATA_DIR), para a verificacao nao tocar nas
        configuracoes de quem usa esta maquina. O executavel nao tem
        console: o que conta e o codigo de saida e o relatorio JSON.
    #>
    param(
        [Parameter(Mandatory)][string]$Executavel,
        [int]$TempoLimiteSegundos = 300
    )

    $pasta = Join-Path ([System.IO.Path]::GetTempPath()) ("filemorph-verificacao-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $pasta | Out-Null
    $relatorio = Join-Path $pasta 'relatorio.json'
    $anterior = $env:FILEMORPH_DATA_DIR
    $env:FILEMORPH_DATA_DIR = Join-Path $pasta 'dados'
    try {
        $processo = Start-Process -FilePath $Executavel -ArgumentList @('--smoke-test', "`"$relatorio`"") -PassThru
        if (-not $processo.WaitForExit($TempoLimiteSegundos * 1000)) {
            Stop-Process -Id $processo.Id -Force -ErrorAction SilentlyContinue
            throw "A verificacao de '$Executavel' passou de $TempoLimiteSegundos s e foi interrompida."
        }
        if (-not (Test-Path -LiteralPath $relatorio)) {
            throw "A verificacao de '$Executavel' terminou (codigo $($processo.ExitCode)) sem gravar o relatorio."
        }
        $dados = Get-Content -LiteralPath $relatorio -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($item in $dados.checks) {
            if ($item.ok) {
                Write-Ok "$($item.name)"
            } else {
                Write-Warn "$($item.name): $($item.detail)"
            }
        }
        if (-not $dados.ok -or $processo.ExitCode -ne 0) {
            throw "A verificacao do executavel falhou (codigo $($processo.ExitCode)). Relatorio: $relatorio"
        }
        Write-Info "Python usado pelo executavel: $($dados.python_dll)"
        Remove-Item -LiteralPath $pasta -Recurse -Force -ErrorAction SilentlyContinue
    } finally {
        $env:FILEMORPH_DATA_DIR = $anterior
    }
}

function Write-Sha256 {
    <# Grava <arquivo>.sha256 no formato do sha256sum e devolve o hash. #>
    param([Parameter(Mandatory)][string]$Arquivo)
    $hash = (Get-FileHash -LiteralPath $Arquivo -Algorithm SHA256).Hash.ToLowerInvariant()
    $nome = Split-Path -Leaf $Arquivo
    Set-Content -LiteralPath "$Arquivo.sha256" -Value "$hash *$nome" -Encoding ASCII
    return $hash
}

function Remove-VersoesAntigas {
    <#
        Apaga os artefatos de versoes anteriores que ficaram na pasta de
        saida, para ela conter so o da versao atual.

        So e chamada depois que o artefato novo existe e foi verificado:
        um build que falha nunca deixa a pasta sem instalador. Remove
        apenas ARQUIVOS, dentro da pasta passada, cujo nome bate exatamente
        com FileMorph-x.y.z-<Sufixo>.exe (e o .sha256 ao lado) e cuja versao
        seja diferente da atual. Nada de subpastas, nada de curingas soltos.
    #>
    param(
        [Parameter(Mandatory)][string]$Pasta,
        [Parameter(Mandatory)][ValidateSet('setup', 'portable')][string]$Sufixo,
        [Parameter(Mandatory)][string]$VersaoAtual
    )

    $pastaDist = [System.IO.Path]::GetFullPath($Dist).TrimEnd('\')
    $alvo = [System.IO.Path]::GetFullPath($Pasta).TrimEnd('\')
    if ((Split-Path -Parent $alvo) -ne $pastaDist) {
        throw "Recusando limpar '$alvo': so pastas diretamente dentro de '$pastaDist' sao limpas."
    }
    if (-not (Test-Path -LiteralPath $alvo -PathType Container)) { return }

    $padrao = '^FileMorph-(\d+\.\d+\.\d+)-' + $Sufixo + '\.exe(\.sha256)?$'
    Get-ChildItem -LiteralPath $alvo -File | ForEach-Object {
        if ($_.Name -match $padrao -and $Matches[1] -ne $VersaoAtual) {
            Remove-Item -LiteralPath $_.FullName -Force
            Write-Info "Removido de uma versao anterior: $($_.Name)"
        }
    }
}


Write-Host ''
Write-Host '  FileMorph - empacotamento' -ForegroundColor White
Write-Host '  -------------------------' -ForegroundColor DarkGray

try {
    $versao = Get-Metadado -Nome '__version__'
    if ($versao -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
        throw "Nao consegui ler uma versao x.y.z valida de app\version.py (lido: '$versao')."
    }
    $publicador = Get-Metadado -Nome 'APP_PUBLISHER' -Padrao 'Antonio Reis'
    $url = Get-Metadado -Nome 'APP_URL' -Padrao 'https://github.com/antonioreis29/FileMorph'
    Write-Info "Versao: $versao"
    Write-Info "Projeto: $Raiz"

    # --- 1) Python ---------------------------------------------------
    Write-Passo '[1/7] Conferindo o Python'

    if ([string]::IsNullOrWhiteSpace($Python)) {
        $Python = Find-Python
    }
    if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
        throw @"
Nenhum Python com o PyInstaller foi encontrado.

Para preparar um ambiente aqui no projeto:

    py -3.13 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements-build.txt -r requirements-dev.txt -c constraints-release.txt
"@
    }
    $sonda = 'import struct, sys; sys.exit(0 if struct.calcsize(''P'') == 8 and sys.version_info >= (3, 12) else 3)'
    $codigo = Invoke-Externo -Programa $Python -Argumentos @('-c', $sonda) -Silencioso
    if ($codigo -ne 0) {
        throw "O Python '$Python' precisa ser 64 bits e 3.12 ou mais novo. O instalador e de 64 bits e o executavel herda a arquitetura do Python que o empacota."
    }
    Write-Ok "Python 64 bits: $Python"

    # --- 2) Testes ---------------------------------------------------
    Write-Passo '[2/7] Testes unitarios'
    if ($PularTestes) {
        Write-Warn 'Pulados por parametro.'
    } elseif ((Invoke-Externo -Programa $Python -Argumentos @('-c', 'import pytest') -Silencioso) -ne 0) {
        Write-Warn 'pytest nao esta instalado neste Python - testes nao rodados (instale requirements-dev.txt).'
    } else {
        $anteriorQt = $env:QT_QPA_PLATFORM
        $env:QT_QPA_PLATFORM = 'offscreen'
        try {
            $codigo = Invoke-Externo -Programa $Python -Argumentos @('-m', 'pytest', (Join-Path $Raiz 'tests'), '-m', 'not integration', '-q')
        } finally {
            $env:QT_QPA_PLATFORM = $anteriorQt
        }
        if ($codigo -ne 0) { throw "Os testes unitarios falharam (codigo $codigo). Nada foi empacotado." }
        Write-Ok 'Testes unitarios passaram.'
    }

    # --- 3) Executavel -----------------------------------------------
    Write-Passo '[3/7] Empacotando o executavel (PyInstaller, pasta)'
    Write-Info 'Isso costuma levar de um a tres minutos.'

    $argumentos = @('-m', 'PyInstaller', (Join-Path $Raiz 'FileMorph.spec'), '--noconfirm',
                    '--distpath', $Dist, '--workpath', $Build)
    if (-not $SemLimpar) {
        # --clean descarta o cache de analise. Sem isso, um arquivo
        # removido do projeto pode continuar entrando no pacote.
        $argumentos += '--clean'
    }
    $codigo = Invoke-Externo -Programa $Python -Argumentos $argumentos
    if ($codigo -ne 0) { throw "O PyInstaller falhou (codigo $codigo)." }

    $pastaApp = Join-Path $Dist 'FileMorph'
    $exe = Join-Path $pastaApp 'FileMorph.exe'
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "O PyInstaller terminou sem erro mas o '$exe' nao apareceu."
    }
    $tamanho = [math]::Round(((Get-ChildItem -LiteralPath $pastaApp -Recurse -File |
                               Measure-Object -Property Length -Sum).Sum / 1MB), 1)
    Write-Ok "dist\FileMorph\FileMorph.exe  ($tamanho MB na pasta)"

    # --- 4) Verificacao ----------------------------------------------
    Write-Passo '[4/7] Verificando o pacote'
    Test-PacoteLimpo -Pasta $pastaApp
    Write-Ok 'Nenhum arquivo de desenvolvimento no pacote.'
    Invoke-SmokeTest -Executavel $exe

    # --- 5) Instalador -----------------------------------------------
    $setup = $null
    if ($SomenteExe) {
        Write-Passo '[5/7] Instalador ignorado por parametro'
        Write-Warn 'dist\FileMorph\ nao e para ser enviado sozinho: o que se compartilha e o setup.exe.'
    } else {
        Write-Passo '[5/7] Montando o instalador (Inno Setup)'
        $iscc = Find-Inno
        if (-not $iscc) {
            throw @"
Inno Setup 6 nao encontrado - o instalador nao foi montado.

Para instalar:
    winget install JRSoftware.InnoSetup
  ou baixe em https://jrsoftware.org/isdl.php

Para gerar so o executavel, rode com -SomenteExe.
"@
        }
        Write-Info "ISCC: $iscc"
        $codigo = Invoke-Externo -Programa $iscc -Argumentos @(
            "/DMyAppVersion=$versao",
            "/DMyAppPublisher=$publicador",
            "/DMyAppURL=$url",
            (Join-Path $Raiz 'installer\FileMorph.iss')
        )
        if ($codigo -ne 0) { throw "O Inno Setup falhou (codigo $codigo)." }

        $setup = Join-Path $Dist "installer\FileMorph-$versao-setup.exe"
        if (-not (Test-Path -LiteralPath $setup)) {
            throw "O Inno Setup terminou sem erro mas '$setup' nao foi encontrado."
        }
        $mb = [math]::Round(((Get-Item -LiteralPath $setup).Length / 1MB), 1)
        Write-Ok "$setup  ($mb MB)"
    }

    # --- 6) Hash -----------------------------------------------------
    Write-Passo '[6/7] SHA-256'
    if ($setup) {
        $hash = Write-Sha256 -Arquivo $setup
        Write-Ok "$hash  FileMorph-$versao-setup.exe"
        Remove-VersoesAntigas -Pasta (Split-Path -Parent $setup) -Sufixo 'setup' -VersaoAtual $versao
    } else {
        Write-Info 'Sem instalador, sem hash.'
    }

    # --- 7) Portatil -------------------------------------------------
    $portatilExe = $null
    if ($Portatil) {
        Write-Passo '[7/7] Executavel portatil (PyInstaller, arquivo unico)'
        $distPortatil = Join-Path $Dist 'portable'
        $argumentos = @('-m', 'PyInstaller', (Join-Path $Raiz 'FileMorph-portable.spec'), '--noconfirm',
                        '--distpath', $distPortatil, '--workpath', (Join-Path $Build 'portable'))
        if (-not $SemLimpar) { $argumentos += '--clean' }
        $codigo = Invoke-Externo -Programa $Python -Argumentos $argumentos
        if ($codigo -ne 0) { throw "O PyInstaller falhou no portatil (codigo $codigo)." }

        $portatilExe = Join-Path $distPortatil "FileMorph-$versao-portable.exe"
        if (-not (Test-Path -LiteralPath $portatilExe)) {
            throw "O PyInstaller terminou sem erro mas '$portatilExe' nao apareceu."
        }
        $mb = [math]::Round(((Get-Item -LiteralPath $portatilExe).Length / 1MB), 1)
        Write-Ok "$portatilExe  ($mb MB)"
        Invoke-SmokeTest -Executavel $portatilExe
        $hash = Write-Sha256 -Arquivo $portatilExe
        Write-Ok "$hash  FileMorph-$versao-portable.exe"
        Remove-VersoesAntigas -Pasta $distPortatil -Sufixo 'portable' -VersaoAtual $versao
    } else {
        Write-Passo '[7/7] Portatil nao pedido (use -Portatil)'
    }

    Write-Host ''
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host '  Empacotamento concluido.' -ForegroundColor Green
    if ($setup) {
        Write-Host "  Para compartilhar: $setup"
    }
    if ($portatilExe) {
        Write-Host "  Portatil (opcional): $portatilExe"
    }
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
