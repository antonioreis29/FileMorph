# Instaladores antigos (legado)

Estes scripts instalavam e abriam o FileMorph **a partir do código-fonte**,
usando um Python instalado na máquina do usuário. Eles foram substituídos pelo
instalador de verdade — `dist/installer/FileMorph-<versão>-setup.exe`, gerado
por `empacotar.ps1` —, que não precisa de Python nenhum.

Continuam aqui para quem desenvolve e quer rodar ou instalar o aplicativo
direto do código:

| Arquivo | O que faz |
|---|---|
| `FileMorph.bat` | Abre o aplicativo com o Python da máquina (instala as dependências na primeira vez). |
| `FileMorph (sem console).vbs` | O mesmo, sem a janela preta do terminal. |
| `Instalar FileMorph.bat` | Roda o `install.ps1` com duplo clique. |
| `install.ps1` | Copia o projeto para `%LOCALAPPDATA%\Programs\FileMorph`, cria um ambiente virtual, atalhos e a entrada em Configurações → Aplicativos. |
| `desinstalar.ps1` | Remove o que o `install.ps1` criou. É copiado para a raiz da instalação, e é de lá que roda. |

Os scripts localizam a pasta do projeto a partir do próprio caminho (dois
níveis acima desta pasta) e nunca a partir do diretório de trabalho. O
`desinstalar.ps1` recusa apagar qualquer pasta que tenha `.git` ou que não
tenha o marcador de uma instalação.

**Não use os dois instaladores na mesma pasta.** O `install.ps1` e o `setup.exe`
instalam, por padrão, no mesmo lugar (`%LOCALAPPDATA%\Programs\FileMorph`), mas
registram entradas diferentes em Configurações → Aplicativos. Desinstale um antes
de instalar o outro.
