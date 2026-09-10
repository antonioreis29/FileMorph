@echo off
REM ============================================================
REM  FileMorph - instalador (duplo clique)
REM
REM  Este arquivo existe por um motivo especifico do Windows: um
REM  arquivo .ps1 NAO executa com duplo clique. Por seguranca, o
REM  Windows associa a extensao .ps1 ao Bloco de Notas, entao
REM  clicar no install.ps1 apenas abre o codigo como texto.
REM
REM  Um .bat, ao contrario, executa com duplo clique. Este aqui
REM  chama o PowerShell explicitamente e manda ele rodar o
REM  install.ps1 que esta ao lado.
REM ============================================================

title Instalar FileMorph
cd /d "%~dp0"

if not exist "install.ps1" goto sem_script

REM -ExecutionPolicy Bypass vale SO para esta chamada: nao altera a
REM politica da maquina, apenas permite que este script rode agora.
REM Sem isso, a politica padrao do Windows (Restricted) recusaria o
REM install.ps1 mesmo sendo um arquivo local.
REM -NoProfile ignora o perfil do usuario, para que personalizacoes
REM do PowerShell dele nao interfiram na instalacao.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "CODIGO=%ERRORLEVEL%"

echo.
if not "%CODIGO%"=="0" goto falhou

echo Pressione qualquer tecla para fechar esta janela.
pause >nul
exit /b 0


:sem_script
echo Nao encontrei o arquivo install.ps1 nesta pasta.
echo.
echo O "Instalar FileMorph.bat" precisa ficar na mesma pasta que o
echo install.ps1 - a pasta do FileMorph que voce baixou.
echo.
pause
exit /b 1

:falhou
echo A instalacao terminou com erro (codigo %CODIGO%).
echo A mensagem acima explica o que aconteceu.
echo.
pause
exit /b %CODIGO%
