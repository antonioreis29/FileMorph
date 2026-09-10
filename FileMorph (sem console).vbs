' ============================================================
'  FileMorph - abre o aplicativo sem nenhuma janela de console
'  visivel.
'
'  Por baixo, isto so chama o FileMorph.bat de sempre com a
'  janela escondida: toda a logica de abrir o Python, checar e
'  instalar dependencias continua exatamente a mesma, num unico
'  lugar (FileMorph.bat) para nao haver duas versoes dela para
'  manter.
'
'  A unica diferenca de comportamento: se o FileMorph.bat
'  terminar com erro (Python nao encontrado, dependencia que nao
'  instalou, o app fechando sozinho), em vez do texto ficar preso
'  numa janela de console que ninguem viu abrir, ele aparece
'  numa caixa de mensagem normal do Windows.
'
'  Este arquivo deve ficar na mesma pasta que o FileMorph.bat.
' ============================================================

Option Explicit

Dim shell, fso, scriptDir, batPath, logPath, command, exitCode
Dim logFile, output

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\FileMorph.bat"

If Not fso.FileExists(batPath) Then
    MsgBox "Nao encontrei o FileMorph.bat nesta pasta." & vbCrLf & _
           "Mova este arquivo para a pasta onde esta o FileMorph.bat.", _
           vbCritical, "FileMorph"
    WScript.Quit 1
End If

' A saida do .bat vai para um arquivo temporario, para poder ser
' mostrada numa caixa de mensagem caso algo de errado aconteca.
' "< nul" evita que um eventual "pause" dentro do .bat trave para
' sempre esperando uma tecla que nunca vai ser apertada, ja que
' nao ha console visivel para o usuario apertar nada.
logPath = shell.ExpandEnvironmentStrings("%TEMP%") & "\FileMorph_ultima_execucao.log"
command = "cmd /c """"" & batPath & """ < nul > """ & logPath & """ 2>&1"""

' O segundo argumento (0) e o que esconde a janela; o terceiro
' (True) espera o processo terminar antes de continuar, para dar
' tempo de ler o resultado.
exitCode = shell.Run(command, 0, True)

If exitCode <> 0 Then
    output = ""
    If fso.FileExists(logPath) Then
        Dim reader
        Set reader = fso.OpenTextFile(logPath, 1)
        output = reader.ReadAll()
        reader.Close
    End If

    MsgBox "O FileMorph nao conseguiu abrir." & vbCrLf & vbCrLf & output, _
           vbExclamation, "FileMorph"
End If
