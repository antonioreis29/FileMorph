@echo off
REM ============================================================
REM  FileMorph - abre o aplicativo a partir do codigo-fonte, com
REM  duplo clique, usando um Python instalado na maquina.
REM
REM  LEGADO: a forma recomendada de usar o FileMorph e o instalador
REM  (FileMorph-<versao>-setup.exe), que nao precisa de Python.
REM
REM  Este arquivo fica em dev\legacy, dois niveis abaixo da pasta do
REM  projeto, onde esta o main.py.
REM ============================================================

title FileMorph
cd /d "%~dp0..\.."

if not exist "main.py" goto sem_main

REM --- 1) Descobre qual Python usar -------------------------------
REM Prioridade: ambiente virtual .venv (o mesmo criado no README),
REM depois "python" no PATH, depois o launcher "py".
set "PYTHON="

if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

if not defined PYTHON (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=py -3"
)

if not defined PYTHON goto sem_python

REM --- 2) Garante as dependencias --------------------------------
REM PySide6 abre a janela; Pillow converte imagens; pypdf e PyMuPDF
REM cuidam do PDF. Se qualquer uma faltar, instala tudo de uma vez.
%PYTHON% -c "import PySide6, PIL, pypdf, pymupdf" >nul 2>&1
if errorlevel 1 (
    echo Faltam as dependencias do FileMorph.
    echo Instalando agora - isso costuma acontecer so na primeira vez.
    echo.
    %PYTHON% -m pip install -r requirements.txt
    if errorlevel 1 goto sem_dependencias
    echo.
)

REM --- 3) Abre o aplicativo ---------------------------------------
echo Abrindo o FileMorph...
%PYTHON% main.py
if errorlevel 1 goto erro_execucao
exit /b 0


:sem_main
echo Nao encontrei o arquivo main.py dois niveis acima deste arquivo.
echo O FileMorph.bat precisa ficar em dev\legacy, dentro da pasta do FileMorph.
echo.
pause
exit /b 1

:sem_python
echo Nao foi possivel abrir o FileMorph: o Python nao foi encontrado.
echo.
echo Instale o Python 3.12 ou mais novo em https://www.python.org/downloads/
echo e marque a opcao "Add python.exe to PATH" durante a instalacao.
echo.
pause
exit /b 1

:sem_dependencias
echo.
echo Nao foi possivel instalar as dependencias.
echo Verifique sua conexao com a internet e tente de novo.
echo.
pause
exit /b 1

:erro_execucao
echo.
echo O FileMorph fechou com erro.
echo Os detalhes tecnicos ficam no arquivo de log em:
echo    %%APPDATA%%\FileMorph\logs
echo.
pause
exit /b 1
