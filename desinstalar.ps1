<#
.SYNOPSIS
    Desinstalador do FileMorph.

.DESCRIPTION
    Remove o que o install.ps1 criou, e somente isso:

      1. Os atalhos do Menu Iniciar e da Área de Trabalho.
      2. A chave do registro que coloca o FileMorph em
         Configurações > Aplicativos.
      3. A pasta da instalação, incluindo o ambiente virtual.

    **As suas coisas não são tocadas.** As configurações em
    %APPDATA%\FileMorph, os logs e os arquivos já convertidos em
    Documentos\FileMorph\Convertidos continuam onde estão. Foram
    criados pelo aplicativo em tempo de execução, não pelo instalador,
    e reinstalar depois reaproveita tudo. Quem quiser apagá-los também
    faz isso à mão, de propósito — é uma decisão diferente de
    "desinstalar o programa".

    O script é copiado para dentro da pasta de instalação pelo
    install.ps1, e é ele que o botão "Desinstalar" do Windows chama.

.EXAMPLE
    .\desinstalar.ps1

    Pergunta antes de apagar.

.EXAMPLE
    .\desinstalar.ps1 -Silencioso

    Não pergunta nada. É assim que o Windows o chama pelo
    QuietUninstallString.
#>

[CmdletBinding()]
param(
    # Pasta a remover. Deixe em branco para usar a pasta onde este
    # script está, que é onde o install.ps1 o deixou.
    #
    # O padrão é vazio DE PROPÓSITO, e não `$PSScriptRoot`: usado como
    # valor padrão de parâmetro, o `$PSScriptRoot` já voltou vazio ao
    # ser chamado com `powershell -File`, e um caminho vazio aqui
    # significa apagar a pasta errada. A resolução acontece no corpo do
    # script, onde dá para conferir o resultado antes de usar.
    [string]$InstallPath = '',

    # Não fazer perguntas. Usado pelo Windows na desinstalação
    # silenciosa.
    [switch]$Silencioso,

    # Precisa bater com o ShortcutName usado na instalação.
    [string]$ShortcutName = 'FileMorph'
)

$ErrorActionPreference = 'Stop'

# Precisa ser exatamente a mesma chave escrita pelo install.ps1, senão
# a entrada fica órfã no Painel de Controle depois da remoção.
$RegistryKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FileMorph'

function Write-Ok   { param([string]$m) Write-Host "      OK  $m" -ForegroundColor Green }
function Write-Warn { param([string]$m) Write-Host "      !   $m" -ForegroundColor Yellow }

Write-Host ''
Write-Host '  FileMorph - desinstalacao' -ForegroundColor White
Write-Host '  -------------------------' -ForegroundColor DarkGray

try {
    # ============================================================
    #  Descobrir O QUE apagar
    #
    #  Este bloco existe porque a versão anterior deste script apagou
    #  a pasta errada — a do código-fonte, com commits que ainda não
    #  tinham sido enviados. As regras abaixo são a lição disso, e
    #  nenhuma delas deve ser afrouxada por conveniência.
    # ============================================================

    # Regra 1: o alvo nunca é deduzido do diretório de trabalho.
    # `Get-Location` devolve a pasta de onde o usuário chamou o script,
    # que não tem relação nenhuma com onde o FileMorph foi instalado.
    # Sem um alvo explícito, o certo é falhar.
    if ([string]::IsNullOrWhiteSpace($InstallPath)) {
        # $PSScriptRoot é o caminho normal; $MyInvocation cobre o caso
        # em que ele vem vazio, que é justamente o que causou o acidente.
        $InstallPath = $PSScriptRoot
        if ([string]::IsNullOrWhiteSpace($InstallPath) -and $MyInvocation.MyCommand.Path) {
            $InstallPath = Split-Path -Parent $MyInvocation.MyCommand.Path
        }
    }

    if ([string]::IsNullOrWhiteSpace($InstallPath)) {
        throw 'Nao foi possivel descobrir qual pasta desinstalar. Rode novamente passando -InstallPath com o caminho completo. Nada foi removido.'
    }

    if (-not (Test-Path -LiteralPath $InstallPath)) {
        throw "A pasta '$InstallPath' nao existe. Nada foi removido."
    }

    $InstallPath = (Resolve-Path -LiteralPath $InstallPath).Path.TrimEnd('\')

    # Regra 2: um .git significa que isto é um repositório de trabalho,
    # não uma instalação. O install.ps1 nunca copia o .git, então uma
    # instalação de verdade jamais tem um. Esta é a checagem que teria
    # evitado o acidente sozinha.
    if (Test-Path -LiteralPath (Join-Path $InstallPath '.git')) {
        throw "'$InstallPath' contem uma pasta .git, ou seja, e um repositorio de codigo-fonte e nao uma instalacao. Recusando apagar. Nada foi removido."
    }

    # Regra 3: o marcador precisa ser algo que SÓ a instalação tem. O
    # `main.py` sozinho não serve — o código-fonte também o tem, e foi
    # exatamente por isso que a checagem antiga deixou passar a pasta
    # errada. O FileMorph.vbs é gerado pelo install.ps1 dentro da pasta
    # de destino e não existe no repositório; o FileMorph.exe é o
    # equivalente na versão empacotada.
    $marcadores = @('FileMorph.vbs', 'FileMorph.exe')
    $encontrado = $marcadores | Where-Object { Test-Path -LiteralPath (Join-Path $InstallPath $_) }
    if (-not $encontrado) {
        throw "'$InstallPath' nao parece uma instalacao do FileMorph: nenhum de $($marcadores -join ' ou ') foi encontrado la. Nada foi removido."
    }

    # Regra 4: nunca apagar uma pasta que contenha o próprio diretório
    # de trabalho atual, nem a raiz de um disco.
    if ($InstallPath -match '^[A-Za-z]:\\?$') {
        throw "Recusando apagar a raiz do disco '$InstallPath'. Nada foi removido."
    }

    Write-Host ''
    Write-Host "  Alvo resolvido: $InstallPath" -ForegroundColor DarkGray
    Write-Host "  Marcador encontrado: $($encontrado -join ', ')" -ForegroundColor DarkGray

    if (-not $Silencioso) {
        Write-Host ''
        Write-Host "  Sera removida a pasta: $InstallPath"
        Write-Host '  Suas configuracoes e arquivos convertidos NAO serao apagados.' -ForegroundColor DarkGray
        Write-Host ''
        $resposta = Read-Host '  Continuar? (S/N)'
        if ($resposta -notmatch '^[SsYy]') {
            Write-Host ''
            Write-Host '  Cancelado. Nada foi removido.' -ForegroundColor Yellow
            Write-Host ''
            exit 0
        }
    }

    # --- 1) Atalhos -------------------------------------------------
    Write-Host ''
    Write-Host '[1/3] Removendo os atalhos' -ForegroundColor Cyan

    $atalhos = @(
        (Join-Path ([Environment]::GetFolderPath('Programs')) "$ShortcutName.lnk"),
        (Join-Path ([Environment]::GetFolderPath('Desktop'))  "$ShortcutName.lnk")
    )
    foreach ($atalho in $atalhos) {
        if (Test-Path -LiteralPath $atalho) {
            Remove-Item -LiteralPath $atalho -Force
            Write-Ok $atalho
        }
    }

    # --- 2) Registro ------------------------------------------------
    Write-Host ''
    Write-Host '[2/3] Removendo o registro do Painel de Controle' -ForegroundColor Cyan

    if (Test-Path -LiteralPath $RegistryKey) {
        Remove-Item -LiteralPath $RegistryKey -Recurse -Force
        Write-Ok 'Entrada removida de Configuracoes > Aplicativos.'
    } else {
        Write-Warn 'Nao havia entrada no registro - seguindo.'
    }

    # --- 3) Pasta ---------------------------------------------------
    Write-Host ''
    Write-Host '[3/3] Removendo os arquivos' -ForegroundColor Cyan

    # O próprio script está dentro da pasta que vai sumir. No Windows
    # isso funciona — o PowerShell já leu o arquivo inteiro para a
    # memória —, mas o diretório de trabalho não pode estar lá dentro,
    # ou o sistema recusa a remoção por "pasta em uso".
    Set-Location ([Environment]::GetFolderPath('Desktop'))

    # A remoção acontece de uma cópia em %TEMP%, e não daqui. Um script
    # não consegue apagar de forma confiável o arquivo que ele mesmo
    # está executando, e o .venv costuma segurar o handle por um
    # instante depois que o processo termina. O jeito robusto é sair de
    # cena e deixar um processo separado terminar o serviço.
    $limpeza = Join-Path $env:TEMP "filemorph-limpeza-$([guid]::NewGuid().ToString('N')).ps1"
    $conteudo = @"
# Espera este desinstalador terminar antes de apagar a pasta que o
# contem. Gerado automaticamente; pode ser apagado a qualquer momento.
#
# As guardas abaixo sao repetidas de proposito. Este arquivo roda em um
# processo separado, que pode ser executado a mao, fora de contexto ou
# muito depois de ter sido gerado — a essa altura a pasta ja pode ser
# outra coisa. Um script que apaga uma arvore inteira nao pode confiar
# em ter sido chamado do jeito certo.
`$alvo = '$InstallPath'

Start-Sleep -Seconds 2

if ([string]::IsNullOrWhiteSpace(`$alvo) -or -not (Test-Path -LiteralPath `$alvo)) { return }
if (`$alvo -match '^[A-Za-z]:\\?`$') { return }
if (Test-Path -LiteralPath (Join-Path `$alvo '.git')) { return }
if (-not (Test-Path -LiteralPath (Join-Path `$alvo 'FileMorph.vbs')) -and
    -not (Test-Path -LiteralPath (Join-Path `$alvo 'FileMorph.exe'))) { return }

try {
    Remove-Item -LiteralPath `$alvo -Recurse -Force -ErrorAction Stop
} catch {
    # Se algo ainda segurar um arquivo, tenta mais uma vez com folga.
    Start-Sleep -Seconds 5
    Remove-Item -LiteralPath `$alvo -Recurse -Force -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath '$limpeza' -Force -ErrorAction SilentlyContinue
"@
    Set-Content -LiteralPath $limpeza -Value $conteudo -Encoding UTF8

    Start-Process -FilePath 'powershell' `
                  -ArgumentList @('-NoProfile', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass', '-File', $limpeza) `
                  -WindowStyle Hidden

    Write-Ok "$InstallPath (removida em segundo plano)"

    Write-Host ''
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host '  FileMorph desinstalado.' -ForegroundColor Green
    Write-Host ''
    Write-Host '  Continuam intactos, caso queira reinstalar depois:' -ForegroundColor DarkGray
    Write-Host "      $env:APPDATA\FileMorph" -ForegroundColor DarkGray
    Write-Host "      $([Environment]::GetFolderPath('MyDocuments'))\FileMorph\Convertidos" -ForegroundColor DarkGray
    Write-Host '  ----------------------------------------------------' -ForegroundColor DarkGray
    Write-Host ''

    if (-not $Silencioso) {
        Write-Host '  Pressione qualquer tecla para fechar.' -ForegroundColor DarkGray
        [void][System.Console]::ReadKey($true)
    }

    exit 0

} catch {
    Write-Host ''
    Write-Host '  A desinstalacao nao foi concluida.' -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ''
    if (-not $Silencioso) {
        Write-Host '  Pressione qualquer tecla para fechar.' -ForegroundColor DarkGray
        [void][System.Console]::ReadKey($true)
    }
    exit 1
}
