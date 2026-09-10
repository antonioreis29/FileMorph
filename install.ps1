<#
.SYNOPSIS
    Instalador do FileMorph para Windows, sem exigir privilégios de administrador.

.DESCRIPTION
    O FileMorph roda hoje a partir do código-fonte Python (o empacotamento em
    .exe é uma fase futura do projeto). Este script faz o que um instalador
    faria nesse cenário:

      1. Confere que a pasta de origem é mesmo um FileMorph.
      2. Localiza um Python 3.x utilizável na máquina.
      3. Copia o projeto para %LOCALAPPDATA%\Programs\FileMorph.
      4. Cria um ambiente virtual lá dentro e instala as dependências.
      5. Verifica o FFmpeg (opcional — só avisa se faltar).
      6. Gera um atalho de inicialização que abre o app sem console.
      7. Cria os atalhos no Menu Iniciar e, opcionalmente, na Área de Trabalho.
      8. Registra o aplicativo em Configurações > Aplicativos, com botão
         de desinstalar.

    O script NUNCA toca nas pastas de dados do usuário — configurações em
    %APPDATA%\FileMorph, logs, e a pasta de arquivos convertidos em
    Documentos\FileMorph\Convertidos. Elas são criadas e gerenciadas pelo
    próprio aplicativo em tempo de execução e independem de onde ele está
    instalado, então reinstalar não perde nenhuma preferência.

.EXAMPLE
    .\install.ps1

    Instala a partir da pasta onde o próprio install.ps1 está.

.EXAMPLE
    .\install.ps1 -InstallPath 'D:\Apps\FileMorph' -CreateDesktopShortcut:$false

    Instala em outro lugar e não cria atalho na Área de Trabalho.
#>

[CmdletBinding()]
param(
    # Pasta de origem: de onde o projeto será copiado. O padrão é a pasta
    # onde este script está, que é o caso normal (rodar o install.ps1 de
    # dentro do projeto recém-baixado).
    [string]$SourcePath = $PSScriptRoot,

    # Pasta de destino. %LOCALAPPDATA%\Programs é o lugar convencional para
    # aplicativos instalados por usuário no Windows — diferente de
    # C:\Program Files, ele não exige elevação de privilégio.
    [string]$InstallPath = (Join-Path $env:LOCALAPPDATA 'Programs\FileMorph'),

    # Versão mínima do Python, conforme documentado no README do projeto.
    [version]$MinimumPythonVersion = '3.12',

    # Criar também um atalho na Área de Trabalho, além do Menu Iniciar.
    [bool]$CreateDesktopShortcut = $true,

    # Nome que aparece nos atalhos.
    [string]$ShortcutName = 'FileMorph'
)

# Faz qualquer erro de cmdlet virar exceção, para o try/catch principal
# capturar tudo em um lugar só. Comandos nativos (python, pip, robocopy)
# não obedecem a isso e têm o código de saída conferido à mão.
$ErrorActionPreference = 'Stop'

# Pastas e arquivos que não devem ser copiados para a instalação:
# controle de versão, caches, e principalmente o .venv da origem — um
# ambiente virtual carrega caminhos absolutos gravados dentro dele e
# simplesmente não funciona se for movido de lugar.
$ExcludedDirectories = @('.git', '.venv', 'venv', 'env', '__pycache__', '.pytest_cache', 'build', 'dist', '.vscode', '.idea')
$ExcludedFiles = @('*.pyc', '*.pyo', '*.log', 'FileMorph (sem console).vbs')


# ============================================================
#  Funções auxiliares
# ============================================================

$script:CurrentStep = 0

function Write-Step {
    param([string]$Message)
    $script:CurrentStep++
    Write-Host ''
    Write-Host "[$script:CurrentStep/8] $Message" -ForegroundColor Cyan
}

function Write-Detail {
    param([string]$Message)
    Write-Host "      $Message" -ForegroundColor DarkGray
}

function Write-Ok {
    param([string]$Message)
    Write-Host "      OK  $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "      !   $Message" -ForegroundColor Yellow
}

function Invoke-Capture {
    <#
        Executa um programa externo e devolve a saída e o código de retorno.

        O PowerShell 5.1 transforma cada linha de stderr de um executável
        nativo em um ErrorRecord, o que dispararia o $ErrorActionPreference
        = 'Stop' mesmo quando o programa terminou bem. Por isso a preferência
        é afrouxada só durante a chamada e restaurada logo em seguida.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @()
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $FilePath @Arguments 2>$null
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }

    return [pscustomobject]@{
        Output   = (($output | Out-String).Trim())
        ExitCode = $code
    }
}

function Invoke-Native {
    <#
        Executa um programa externo deixando a saída aparecer na tela (útil
        para operações demoradas, como o pip) e falha se o código de retorno
        não for zero.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory)][string]$ErrorMessage
    )

    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $FilePath @Arguments
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }

    if ($code -ne 0) {
        throw "$ErrorMessage (código de saída $code)."
    }
}

function Find-PythonCommand {
    <#
        Procura um Python utilizável e devolve como executá-lo.

        A ordem importa: o launcher oficial "py -3" vem primeiro porque
        resolve a versão certa mesmo com várias instaladas. O "python" do
        PATH vem depois, e a versão é sempre conferida de verdade — no
        Windows existe um atalho falso de python.exe que só abre a Microsoft
        Store, e ele não sobrevive a esta checagem.
    #>
    param([version]$Minimum)

    $candidates = @(
        [pscustomobject]@{ File = 'py';      Prefix = @('-3') },
        [pscustomobject]@{ File = 'python';  Prefix = @() },
        [pscustomobject]@{ File = 'python3'; Prefix = @() }
    )

    foreach ($candidate in $candidates) {
        $resolved = Get-Command $candidate.File -ErrorAction SilentlyContinue
        if (-not $resolved) {
            continue
        }

        # Nada de aspas duplas dentro do -c: o PowerShell 5.1 as mastiga ao
        # repassar argumentos para executaveis nativos, e o Python receberia
        # um comando quebrado. O sintoma e cruel - esta funcao concluiria que
        # nao ha Python nenhum numa maquina que tem Python instalado.
        $probe = @($candidate.Prefix) + @('-c', 'import sys; print(sys.version.split()[0])')
        $result = Invoke-Capture -FilePath $candidate.File -Arguments $probe

        if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.Output)) {
            continue
        }

        $parsed = $null
        if (-not [version]::TryParse($result.Output, [ref]$parsed)) {
            continue
        }

        Write-Detail "Encontrado: $($candidate.File) $($candidate.Prefix -join ' ') -> Python $parsed"

        if ($parsed -lt $Minimum) {
            Write-Warn "Python $parsed e mais antigo que o minimo exigido ($Minimum) - ignorando."
            continue
        }

        return [pscustomobject]@{
            File    = $candidate.File
            Prefix  = $candidate.Prefix
            Version = $parsed
        }
    }

    return $null
}

function Get-AppVersion {
    <#
        Le a versao de app/version.py.

        Por expressao regular, e nao importando o modulo: neste ponto o
        ambiente virtual pode nem existir ainda, e chamar o Python so
        para ler uma constante seria um custo desnecessario. O formato
        da linha esta documentado no proprio version.py justamente para
        que esta leitura continue valendo.
    #>
    param([Parameter(Mandatory)][string]$ProjectPath)

    $arquivo = Join-Path $ProjectPath 'app\version.py'
    if (-not (Test-Path -LiteralPath $arquivo)) {
        return '0.0.0'
    }

    $conteudo = Get-Content -LiteralPath $arquivo -Raw
    if ($conteudo -match '__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"') {
        return $Matches[1]
    }

    # Uma versao invalida faria o Windows recusar a entrada inteira, o
    # que e pior do que mostrar uma versao generica.
    return '0.0.0'
}


function New-Shortcut {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$TargetPath,
        [string]$WorkingDirectory,
        [string]$IconLocation,
        [string]$Description
    )

    $shell = New-Object -ComObject WScript.Shell
    try {
        $shortcut = $shell.CreateShortcut($Path)
        $shortcut.TargetPath = $TargetPath
        if ($WorkingDirectory) { $shortcut.WorkingDirectory = $WorkingDirectory }
        if ($IconLocation)     { $shortcut.IconLocation = $IconLocation }
        if ($Description)      { $shortcut.Description = $Description }
        $shortcut.Save()
    } finally {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
    }
}


# ============================================================
#  Instalação
# ============================================================

Write-Host ''
Write-Host '  FileMorph - instalacao' -ForegroundColor White
Write-Host '  ----------------------' -ForegroundColor DarkGray

try {

    # --- 1) Conferir a origem ---------------------------------------
    Write-Step 'Conferindo a pasta de origem'

    if ([string]::IsNullOrWhiteSpace($SourcePath)) {
        # Acontece quando o script e executado de um jeito que nao define
        # $PSScriptRoot (colado no terminal, por exemplo).
        $SourcePath = (Get-Location).Path
    }

    $SourcePath = (Resolve-Path -LiteralPath $SourcePath).Path
    $mainScript = Join-Path $SourcePath 'main.py'
    $requirements = Join-Path $SourcePath 'requirements.txt'

    if (-not (Test-Path -LiteralPath $mainScript)) {
        throw "Nao encontrei o main.py em '$SourcePath'. Rode este script de dentro da pasta do FileMorph."
    }
    if (-not (Test-Path -LiteralPath $requirements)) {
        throw "Nao encontrei o requirements.txt em '$SourcePath'."
    }

    Write-Ok "Origem: $SourcePath"

    # Instalar a pasta em cima dela mesma nao faria sentido e ainda
    # arriscaria destruir a origem no meio da copia.
    $sameFolder = $false
    if (Test-Path -LiteralPath $InstallPath) {
        $resolvedInstall = (Resolve-Path -LiteralPath $InstallPath).Path
        if ($resolvedInstall -eq $SourcePath) {
            $sameFolder = $true
        }
    }


    # --- 2) Localizar o Python --------------------------------------
    Write-Step 'Procurando o Python'

    $python = Find-PythonCommand -Minimum $MinimumPythonVersion

    if (-not $python) {
        throw @"
Nenhum Python $MinimumPythonVersion ou mais novo foi encontrado nesta maquina.

Para instalar:

  Opcao 1 (recomendada) - pelo winget, no terminal:
      winget install Python.Python.3.12

  Opcao 2 - manualmente:
      Baixe em https://www.python.org/downloads/
      e marque "Add python.exe to PATH" durante a instalacao.

Depois de instalar, feche e abra o terminal e rode este script de novo.
"@
    }

    Write-Ok "Python $($python.Version) sera usado para criar o ambiente."


    # --- 3) Copiar o projeto ----------------------------------------
    Write-Step 'Copiando os arquivos do aplicativo'

    if ($sameFolder) {
        Write-Detail 'A origem ja e a pasta de instalacao - nada a copiar.'
        Write-Ok "Destino: $InstallPath"
    } else {
        if (-not (Test-Path -LiteralPath $InstallPath)) {
            New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
        }

        # O robocopy e usado por causa dos filtros: /XD e /XF excluem por
        # nome em qualquer nivel da arvore, o que resolve os __pycache__
        # espalhados sem precisar varrer a pasta manualmente.
        # Um .venv que ja exista no destino e preservado - ele esta na
        # lista de exclusao, entao o robocopy nao o toca.
        $robocopyArgs = @(
            $SourcePath,
            $InstallPath,
            '/E',           # subpastas, inclusive vazias
            '/NFL',         # sem lista de arquivos
            '/NDL',         # sem lista de pastas
            '/NJH',         # sem cabecalho
            '/NJS',         # sem resumo
            '/NP',          # sem percentual
            '/R:2',         # 2 tentativas por arquivo
            '/W:1'          # 1 segundo entre tentativas
        )
        $robocopyArgs += '/XD'
        $robocopyArgs += $ExcludedDirectories
        $robocopyArgs += '/XF'
        $robocopyArgs += $ExcludedFiles

        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & robocopy @robocopyArgs | Out-Null
            $robocopyCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previous
        }

        # O robocopy usa codigos de saida como mapa de bits: de 0 a 7 sao
        # variacoes de sucesso (nada a copiar, arquivos copiados, extras
        # encontrados...). A partir de 8 e que houve falha de verdade.
        if ($robocopyCode -ge 8) {
            throw "Falha ao copiar os arquivos para '$InstallPath' (robocopy retornou $robocopyCode)."
        }

        Write-Ok "Destino: $InstallPath"
    }


    # --- 4) Ambiente virtual e dependencias -------------------------
    Write-Step 'Preparando o ambiente virtual e as dependencias'

    $venvPath = Join-Path $InstallPath '.venv'
    $venvPython = Join-Path $venvPath 'Scripts\python.exe'
    $venvPythonw = Join-Path $venvPath 'Scripts\pythonw.exe'

    if (Test-Path -LiteralPath $venvPython) {
        Write-Detail 'Ambiente virtual ja existe - reaproveitando.'
    } else {
        Write-Detail 'Criando o ambiente virtual (.venv)...'
        $venvArgs = @($python.Prefix) + @('-m', 'venv', $venvPath)
        Invoke-Native -FilePath $python.File -Arguments $venvArgs -ErrorMessage 'Nao foi possivel criar o ambiente virtual'
    }

    if (-not (Test-Path -LiteralPath $venvPython)) {
        throw "O ambiente virtual foi criado mas o python.exe nao apareceu em '$venvPath'."
    }

    # O pip antigo que vem em algumas instalacoes nao reconhece os wheels
    # mais novos do PySide6. Atualizar e util, mas nao e motivo para
    # abortar a instalacao se falhar (uma rede corporativa pode bloquear).
    Write-Detail 'Atualizando o pip...'
    $pipUpgrade = Invoke-Capture -FilePath $venvPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', '--disable-pip-version-check')
    if ($pipUpgrade.ExitCode -ne 0) {
        Write-Warn 'Nao foi possivel atualizar o pip - seguindo com a versao atual.'
    }

    Write-Detail 'Instalando PySide6, Pillow, pypdf e PyMuPDF...'
    Write-Detail 'Isso baixa cerca de 150 MB e costuma levar alguns minutos.'
    $installedRequirements = Join-Path $InstallPath 'requirements.txt'
    Invoke-Native -FilePath $venvPython `
                  -Arguments @('-m', 'pip', 'install', '-r', $installedRequirements, '--disable-pip-version-check') `
                  -ErrorMessage 'Nao foi possivel instalar as dependencias'

    # Confirma que as bibliotecas realmente importam - um pip que terminou
    # com sucesso ainda pode deixar um ambiente quebrado.
    # Idem quanto a aspas: o codigo de saida ja diz se os imports funcionaram,
    # sem precisar que o Python imprima nada.
    $verify = Invoke-Capture -FilePath $venvPython -Arguments @('-c', 'import PySide6, PIL, pypdf, pymupdf')
    if ($verify.ExitCode -ne 0) {
        throw "As dependencias foram instaladas mas nao carregam. Detalhes:`n$($verify.Output)"
    }

    Write-Ok 'Dependencias instaladas e verificadas.'


    # --- 5) FFmpeg (opcional) ---------------------------------------
    Write-Step 'Verificando o FFmpeg (audio e video)'

    $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($ffmpeg) {
        $ffmpegVersion = Invoke-Capture -FilePath $ffmpeg.Source -Arguments @('-version')
        $versionLine = ($ffmpegVersion.Output -split "`n")[0]
        Write-Ok "FFmpeg encontrado: $versionLine"
    } else {
        # Ausencia de FFmpeg nao impede a instalacao: o FileMorph abre
        # normalmente e apenas deixa de oferecer audio e video no seletor
        # de formato, exatamente como foi desenhado na Fase 6.
        Write-Warn 'FFmpeg nao encontrado no PATH.'
        Write-Detail ''
        Write-Detail 'O FileMorph vai funcionar normalmente para imagens e PDF, mas as'
        Write-Detail 'conversoes de audio e video (MP3, WAV, FLAC, MP4, MKV, WEBM) nao'
        Write-Detail 'vao aparecer no seletor de formato ate o FFmpeg ser instalado.'
        Write-Detail ''
        Write-Detail 'Para habilita-las depois:'
        Write-Detail '    winget install Gyan.FFmpeg'
        Write-Detail '  ou baixe em https://ffmpeg.org e adicione a pasta bin ao PATH.'
        Write-Detail ''
        Write-Detail 'Nao e preciso reinstalar o FileMorph: basta reabrir o aplicativo.'
    }


    # --- 6) Atalho de inicializacao sem console ---------------------
    Write-Step 'Criando o inicializador'

    if (-not (Test-Path -LiteralPath $venvPythonw)) {
        Write-Warn 'pythonw.exe nao existe neste ambiente - o app usara python.exe.'
    }

    # O pythonw.exe e a versao do interpretador sem console: um aplicativo
    # grafico iniciado por ele simplesmente nao cria janela de terminal.
    # Nao e preciso "ativar" o .venv - chamar o interpretador de dentro
    # dele ja faz o ambiente valer, que e o que a ativacao faria.
    #
    # O .vbs por cima existe por um motivo pratico: um atalho e um duplo
    # clique no Explorer passam a ter um unico ponto de entrada, e quando
    # algo falha o usuario ve uma caixa de mensagem em vez de nada.
    $launcherPath = Join-Path $InstallPath 'FileMorph.vbs'

    $launcherContent = @'
' ============================================================
'  FileMorph - inicializador
'
'  Gerado pelo install.ps1. Abre o aplicativo usando o Python do
'  ambiente virtual da propria pasta, sem janela de console.
'
'  O pythonw.exe e a variante do interpretador destinada a
'  aplicativos graficos: ele nao cria console nenhum. Chamar o
'  interpretador de dentro do .venv ja equivale a ativa-lo.
' ============================================================

Option Explicit

Dim shell, fso, baseDir, interpreter, entryPoint, quote

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
interpreter = baseDir & "\.venv\Scripts\pythonw.exe"
entryPoint = baseDir & "\main.py"

' Algumas instalacoes de Python nao trazem o pythonw.exe; nesse caso
' o python.exe comum resolve, e a janela fica escondida pelo Run.
If Not fso.FileExists(interpreter) Then
    interpreter = baseDir & "\.venv\Scripts\python.exe"
End If

If Not fso.FileExists(interpreter) Then
    MsgBox "O ambiente virtual do FileMorph nao foi encontrado." & vbCrLf & vbCrLf & _
           "Rode o install.ps1 novamente para reinstalar o aplicativo.", _
           vbCritical, "FileMorph"
    WScript.Quit 1
End If

If Not fso.FileExists(entryPoint) Then
    MsgBox "O arquivo main.py nao foi encontrado em:" & vbCrLf & baseDir, _
           vbCritical, "FileMorph"
    WScript.Quit 1
End If

quote = Chr(34)
shell.CurrentDirectory = baseDir

' Janela escondida (0) e sem esperar o app fechar (False).
shell.Run quote & interpreter & quote & " " & quote & entryPoint & quote, 0, False
'@

    Set-Content -LiteralPath $launcherPath -Value $launcherContent -Encoding ASCII
    Write-Ok "Inicializador: $launcherPath"


    # --- 7) Atalhos -------------------------------------------------
    Write-Step 'Criando os atalhos'

    # O atalho usa assets\icons\filemorph.ico quando ele existe. Se o
    # arquivo nao estiver la, o atalho herda o icone do interpretador -
    # feio, mas inofensivo. Basta colocar um .ico nesse caminho e
    # reinstalar para o atalho passar a usa-lo.
    $iconPath = Join-Path $InstallPath 'assets\icons\filemorph.ico'
    if (Test-Path -LiteralPath $iconPath) {
        $iconLocation = $iconPath
    } elseif (Test-Path -LiteralPath $venvPythonw) {
        $iconLocation = "$venvPythonw,0"
    } else {
        $iconLocation = ''
    }

    $startMenuDir = [Environment]::GetFolderPath('Programs')
    $startMenuLink = Join-Path $startMenuDir "$ShortcutName.lnk"

    New-Shortcut -Path $startMenuLink `
                 -TargetPath $launcherPath `
                 -WorkingDirectory $InstallPath `
                 -IconLocation $iconLocation `
                 -Description 'Converta, transforme e junte arquivos localmente'

    Write-Ok "Menu Iniciar: $startMenuLink"

    if ($CreateDesktopShortcut) {
        $desktopDir = [Environment]::GetFolderPath('Desktop')
        $desktopLink = Join-Path $desktopDir "$ShortcutName.lnk"

        New-Shortcut -Path $desktopLink `
                     -TargetPath $launcherPath `
                     -WorkingDirectory $InstallPath `
                     -IconLocation $iconLocation `
                     -Description 'Converta, transforme e junte arquivos localmente'

        Write-Ok "Area de Trabalho: $desktopLink"
    } else {
        Write-Detail 'Atalho na Area de Trabalho desativado por parametro.'
    }


    # --- 8) Registro no Painel de Controle --------------------------
    Write-Step 'Registrando em Configuracoes > Aplicativos'

    # Aquela lista nao e uma varredura do disco: o Windows a monta lendo
    # esta chave do registro. Sem escreve-la, o aplicativo existe em
    # disco mas nao aparece em lugar nenhum e nao tem botao
    # "Desinstalar" — que era exatamente o comportamento anterior.
    #
    # HKCU, e nao HKLM, porque esta e uma instalacao por usuario:
    # escrever em HKLM exigiria elevacao de privilegio, que este
    # instalador faz questao de nao pedir.
    $uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FileMorph'
    $appVersion = Get-AppVersion -ProjectPath $InstallPath

    # O desinstalador acompanha o projeto e foi copiado junto no passo 3.
    $uninstaller = Join-Path $InstallPath 'desinstalar.ps1'
    if (-not (Test-Path -LiteralPath $uninstaller)) {
        Write-Warn 'desinstalar.ps1 nao veio no projeto - a entrada ficara sem botao Desinstalar.'
    }

    # EstimatedSize e informativa e vai em KB, que e a unidade que o
    # Painel de Controle espera. Falhar em calcular nao e motivo para
    # abortar: a coluna apenas fica vazia.
    $tamanhoKb = 0
    try {
        $bytes = (Get-ChildItem -LiteralPath $InstallPath -Recurse -File -ErrorAction SilentlyContinue |
                  Measure-Object -Property Length -Sum).Sum
        if ($bytes) { $tamanhoKb = [int]($bytes / 1KB) }
    } catch {
        Write-Detail 'Nao foi possivel calcular o tamanho da instalacao - seguindo sem ele.'
    }

    if (-not (Test-Path -LiteralPath $uninstallKey)) {
        New-Item -Path $uninstallKey -Force | Out-Null
    }

    # As aspas em volta do caminho do script sao obrigatorias: sem elas,
    # um caminho com espaco (e "Program Files" ou um nome de usuario
    # composto sao comuns) faria o PowerShell tratar cada palavra como
    # um argumento diferente.
    $comandoBase = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$uninstaller`""

    $valores = @{
        DisplayName          = 'FileMorph'
        DisplayVersion       = $appVersion
        Publisher            = 'Antonio Reis'
        DisplayIcon          = $iconPath
        InstallLocation      = $InstallPath
        UninstallString      = $comandoBase
        QuietUninstallString = "$comandoBase -Silencioso"
        URLInfoAbout         = 'https://github.com/antonioreis29/FileMorph'
        # Sem instalador que saiba consertar ou alterar a instalacao, os
        # botoes correspondentes devem sumir em vez de falhar.
        NoModify             = 1
        NoRepair             = 1
    }

    foreach ($nome in $valores.Keys) {
        $valor = $valores[$nome]
        $tipo = if ($valor -is [int]) { 'DWord' } else { 'String' }
        New-ItemProperty -Path $uninstallKey -Name $nome -Value $valor -PropertyType $tipo -Force | Out-Null
    }

    if ($tamanhoKb -gt 0) {
        New-ItemProperty -Path $uninstallKey -Name 'EstimatedSize' -Value $tamanhoKb -PropertyType DWord -Force | Out-Null
    }

    Write-Ok "FileMorph $appVersion aparece agora em Configuracoes > Aplicativos."


    # --- Fim ---------------------------------------------------------
    Write-Host ''
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host '  Instalacao concluida.' -ForegroundColor Green
    Write-Host ''
    Write-Host "  Local da instalacao:  $InstallPath"
    Write-Host "  Para abrir:           Menu Iniciar > $ShortcutName"
    Write-Host ''
    Write-Host '  Suas configuracoes, logs e arquivos convertidos continuam' -ForegroundColor DarkGray
    Write-Host '  onde sempre estiveram e nao foram tocados por este script:' -ForegroundColor DarkGray
    Write-Host "      $env:APPDATA\FileMorph" -ForegroundColor DarkGray
    Write-Host "      $([Environment]::GetFolderPath('MyDocuments'))\FileMorph\Convertidos" -ForegroundColor DarkGray
    Write-Host ''
    Write-Host '  Para desinstalar:     Configuracoes > Aplicativos > FileMorph' -ForegroundColor DarkGray
    Write-Host "                        ou rode $InstallPath\desinstalar.ps1" -ForegroundColor DarkGray
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host ''

    exit 0

} catch {
    Write-Host ''
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host '  A instalacao nao foi concluida.' -ForegroundColor Red
    Write-Host ''
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ''
    Write-Host '  Nada foi alterado nas suas configuracoes ou arquivos.' -ForegroundColor DarkGray
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host ''

    exit 1
}
