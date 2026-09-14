; ============================================================
;  FileMorph - receita do instalador (Inno Setup 6)
;
;  Use o empacotar.ps1 na raiz, que roda o PyInstaller, verifica o
;  executavel e chama isto em seguida. A mao:
;
;      ISCC.exe /DMyAppVersion=1.2.3 installer\FileMorph.iss
;
;  O que este arquivo produz e por que ele existe
;  ---------------------------------------------
;  Um unico setup.exe - dist\installer\FileMorph-<versao>-setup.exe -,
;  que e o arquivo a ser enviado para outra pessoa. Ele instala a pasta
;  que o PyInstaller gerou (dist\FileMorph), que carrega o proprio Python
;  dentro dela: a maquina de destino nao precisa ter Python instalado.
;
;  O FileMorph.exe de dist\FileMorph NAO e um executavel para enviar
;  sozinho: ele depende dos arquivos da pasta ao lado dele.
;
;  O Inno Setup escreve sozinho a chave de desinstalacao no registro, cria
;  os atalhos e gera o unins000.exe. E o mesmo mecanismo que coloca
;  qualquer programa em Configuracoes > Aplicativos.
;
;  A versao NAO e escrita aqui. Ela vem de app/version.py, passada pela
;  linha de comando (/DMyAppVersion=...), para nao haver duas fontes
;  discordando. Compilar sem ela e um erro, e nao um instalador "0.0.0".
; ============================================================

#ifndef MyAppVersion
  #error Passe a versao: ISCC.exe /DMyAppVersion=x.y.z installer\FileMorph.iss (o empacotar.ps1 faz isso sozinho).
#endif

#ifndef MyAppPublisher
  #define MyAppPublisher "Antonio Reis"
#endif
#ifndef MyAppURL
  #define MyAppURL "https://github.com/antonioreis29/FileMorph"
#endif
#define MyAppName "FileMorph"
#define MyAppExeName "FileMorph.exe"

[Setup]
; O AppId identifica o programa entre versoes. Trocar este valor faria
; o Windows tratar a proxima versao como um programa diferente, e o
; usuario acabaria com dois FileMorph instalados lado a lado. Ele deve
; permanecer igual para sempre.
AppId={{7C4E9A21-3F5B-4D8E-9A16-2B7C5D3E8F40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases

; Sem isto, o proprio setup.exe sai com o campo "Versao do arquivo"
; vazio em Propriedades > Detalhes. Nao afeta a instalacao, mas um
; instalador anonimo e mais facil de confundir com outro, e o Windows
; usa esse campo em alguns avisos de seguranca.
VersionInfoVersion={#MyAppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Instalador do {#MyAppName}

; PrivilegesRequired=lowest instala para o usuario atual, sem pedir
; elevacao. O destino cai em %LOCALAPPDATA%\Programs, e nao em
; C:\Program Files, porque escrever la exigiria privilegio de
; administrador.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

DisableWelcomePage=no
LicenseFile=
InfoBeforeFile=
OutputDir=..\dist\installer
OutputBaseFilename=FileMorph-{#MyAppVersion}-setup
SetupIconFile=..\assets\icons\filemorph.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; Um FileMorph aberto segura os arquivos da pasta: o instalador pede para
; fecha-lo antes de substituir, em vez de falhar no meio da copia.
CloseApplications=yes
RestartApplications=no

; lzma2/max e a compressao mais forte disponivel. Compilar demora mais,
; mas o setup.exe e baixado muitas vezes e compilado uma so.
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; O aplicativo e 64 bits porque o Python que o empacota e. Declarar
; isso faz o instalador rodar em modo nativo de 64 bits, sem o
; redirecionamento de pastas que o Windows aplica a programas de 32.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Area de Trabalho"; GroupDescription: "Atalhos:"

[Files]
; O PyInstaller produz dist\FileMorph\ com o .exe e tudo de que ele
; precisa. A pasta inteira entra, recursivamente - o FileMorph.exe
; incluido, pelo mesmo curinga.
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; nowait e postinstall deixam a marcacao "abrir agora" na ultima tela,
; desmarcavel. skipifsilent evita abrir a janela numa instalacao
; automatizada, onde nao haveria ninguem para ve-la.
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Restos que versoes antigas do aplicativo podiam deixar dentro da propria
; pasta. Sem isto, a pasta sobraria vazia-mas-nao-vazia depois de
; desinstalar, porque o Inno Setup so remove o que ele instalou. Nada
; aqui e do usuario: os dados dele ficam fora da pasta do programa.
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\.filemorph_tmp"

[Code]
// As configuracoes do usuario ficam em %APPDATA%\FileMorph e os
// arquivos convertidos em Documentos\FileMorph\Convertidos (ou na pasta
// escolhida nas configuracoes). Nenhum dos dois e tocado na
// desinstalacao, de proposito: foram criados pelo aplicativo em tempo de
// execucao, nao pelo instalador, e apagar o trabalho do usuario nao e o
// que "desinstalar o programa" significa.
//
// Este bloco existe para avisar isso na tela, ja que a pergunta
// aparece toda vez que alguem desinstala algo.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // UninstallSilent e obrigatorio na condicao: uma desinstalacao
  // silenciosa (/VERYSILENT) nao tem ninguem na frente da tela, e uma
  // caixa de mensagem ali trava o processo esperando um clique que
  // nunca vem — quebrando justamente a automacao que o modo silencioso
  // existe para permitir.
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
  begin
    MsgBox('O FileMorph foi removido.' + #13#10 + #13#10 +
           'Suas configuracoes e os arquivos ja convertidos NAO foram apagados. ' +
           'Eles continuam em:' + #13#10 + #13#10 +
           ExpandConstant('{userappdata}\FileMorph') + #13#10 +
           ExpandConstant('{userdocs}\FileMorph\Convertidos'),
           mbInformation, MB_OK);
  end;
end;
