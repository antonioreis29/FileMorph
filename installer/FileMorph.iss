; ============================================================
;  FileMorph - receita do instalador (Inno Setup 6)
;
;  Compile com:
;      ISCC.exe installer\FileMorph.iss
;
;  Ou use o empacotar.ps1 na raiz, que roda o PyInstaller antes e
;  chama isto em seguida.
;
;  O que este arquivo produz e por que ele existe
;  ---------------------------------------------
;  Um unico setup.exe que pode ser enviado para outra pessoa. Ele
;  resolve as duas limitacoes do install.ps1:
;
;    1. O install.ps1 nao pode ser enviado sozinho: ele instala
;       copiando a pasta em que esta, e exige um Python 3.12+ ja
;       instalado na maquina de destino. O executavel do PyInstaller
;       carrega o proprio Python dentro dele, entao nao exige nada.
;    2. O Inno Setup escreve sozinho a chave de desinstalacao no
;       registro, cria os atalhos e gera o unins000.exe. E o mesmo
;       mecanismo que coloca qualquer programa em Configuracoes >
;       Aplicativos — o VS Code, por exemplo, e instalado assim.
;
;  A versao NAO e escrita aqui. Ela e passada pela linha de comando
;  (/DMyAppVersion=...) a partir de app/version.py, para nao haver
;  duas fontes discordando. O valor abaixo so vale se alguem compilar
;  este arquivo a mao, sem passar nada.
; ============================================================

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "FileMorph"
#define MyAppPublisher "Antonio Reis"
#define MyAppURL "https://github.com/antonioreis29/FileMorph"
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

; PrivilegesRequired=lowest instala para o usuario atual, sem pedir
; elevacao — a mesma escolha do install.ps1. O destino cai em
; %LOCALAPPDATA%\Programs, e nao em C:\Program Files, porque escrever
; la exigiria privilegio de administrador.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; O instalador pode ser fechado sem instalar nada; sem isto o Inno
; Setup pergunta antes de sair, o que so atrapalha.
DisableWelcomePage=no
LicenseFile=
InfoBeforeFile=
OutputDir=..\dist\installer
OutputBaseFilename=FileMorph-{#MyAppVersion}-setup
SetupIconFile=..\assets\icons\filemorph.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

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
; precisa. A pasta inteira entra, recursivamente.
Source: "..\dist\{#MyAppName}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
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
; O aplicativo grava logs e temporarios dentro da propria pasta em
; algumas situacoes. Sem isto, a pasta sobra vazia-mas-nao-vazia depois
; de desinstalar, porque o Inno Setup so remove o que ele instalou.
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\.filemorph_tmp"

[Code]
// As configuracoes do usuario ficam em %APPDATA%\FileMorph e os
// arquivos convertidos em Documentos\FileMorph\Convertidos. Nenhum dos
// dois e tocado na desinstalacao, de proposito e pela mesma razao
// documentada no desinstalar.ps1: foram criados pelo aplicativo em
// tempo de execucao, nao pelo instalador, e apagar o trabalho do
// usuario nao e o que "desinstalar o programa" significa.
//
// Este bloco existe para avisar isso na tela, ja que a pergunta
// aparece toda vez que alguem desinstala algo.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox('O FileMorph foi removido.' + #13#10 + #13#10 +
           'Suas configuracoes e os arquivos ja convertidos NAO foram apagados. ' +
           'Eles continuam em:' + #13#10 + #13#10 +
           ExpandConstant('{userappdata}\FileMorph') + #13#10 +
           ExpandConstant('{userdocs}\FileMorph\Convertidos'),
           mbInformation, MB_OK);
  end;
end;
