# FileMorph

**Converta, junte e organize seus arquivos no próprio computador — sem sites, sem internet, sem complicação.**

O FileMorph é um aplicativo para Windows que reúne, em uma janela só, as
transformações de arquivo do dia a dia: mudar uma imagem de formato,
transformar um PDF em imagens, juntar vários documentos em um único PDF,
tirar o áudio de um vídeo, mudar a ordem das páginas de um PDF e muito mais.

A ideia é simples:

> **Arraste seus arquivos → escolha o que fazer → clique → pronto.**

Tudo acontece no seu computador. Nenhum arquivo é enviado para a internet, e
**o arquivo original nunca é alterado**: o resultado é sempre um arquivo novo.

---

## Sumário

- [O que o FileMorph faz](#o-que-o-filemorph-faz)
- [Tipos de arquivo suportados](#tipos-de-arquivo-suportados)
- [Instalação](#instalação)
- [Passo a passo básico](#passo-a-passo-básico)
- [Conhecendo a tela principal](#conhecendo-a-tela-principal)
- [Como usar cada funcionalidade](#como-usar-cada-funcionalidade)
  - [Converter arquivos](#converter-arquivos)
  - [Juntar arquivos em um PDF](#juntar-arquivos-em-um-pdf)
  - [Organizar as páginas de um PDF](#organizar-as-páginas-de-um-pdf)
- [Exemplos rápidos](#exemplos-rápidos)
- [Configurações](#configurações)
- [Onde ficam os arquivos gerados](#onde-ficam-os-arquivos-gerados)
- [Informações importantes e limitações](#informações-importantes-e-limitações)
- [Dúvidas comuns](#dúvidas-comuns)
- [Desinstalar](#desinstalar)
- [Para quem desenvolve o FileMorph](#para-quem-desenvolve-o-filemorph)

---

## O que o FileMorph faz

O FileMorph tem **três modos**, escolhidos no topo da janela:

| Modo | Para que serve |
|---|---|
| **CONVERTER** | Muda o formato de um ou vários arquivos de uma vez. Ex.: fotos JPG para PNG, PDF para imagens, planilha XLSX para CSV, vídeo MP4 para MP3. |
| **JUNTAR** | Une vários arquivos — PDFs, imagens, textos, documentos e planilhas — em **um único PDF**. |
| **ORGANIZAR** | Mostra as páginas de um PDF em miniatura e deixa você **mudar a ordem arrastando as páginas**. |

E em todos eles:

- **Vários arquivos de uma vez** — cada arquivo é processado por conta própria; se um der problema, os outros continuam.
- **Barra de progresso e botão Cancelar** — dá para acompanhar e interromper a qualquer momento, sem deixar arquivos pela metade.
- **Aviso claro quando algo dá errado** — por exemplo, um arquivo corrompido ou protegido por senha aparece na lista com o motivo do erro.
- **Seus originais ficam intactos** — o FileMorph só cria arquivos novos.

---

## Tipos de arquivo suportados

| Tipo | Arquivos que o FileMorph abre | Pode virar |
|---|---|---|
| **Imagens** | PNG, JPG (JPEG), WEBP, BMP, TIFF (TIF), GIF | PNG, JPG, WEBP, BMP, TIFF, GIF ou **PDF** |
| **PDF** | PDF | PNG, JPG, WEBP, BMP, TIFF, GIF (uma imagem por página) ou **TXT** (só o texto) |
| **Documentos** | DOCX (Word) | TXT ou PDF ¹ |
| | TXT (texto) | DOCX ou PDF |
| **Planilhas** | XLSX (Excel) | CSV ou PDF ¹ |
| | CSV | XLSX |
| **Áudio** ² | MP3, WAV, FLAC, OGG, M4A | qualquer um desses cinco |
| **Vídeo** ² | MP4, MKV, AVI, MOV, WEBM | MP4, MKV, WEBM — ou **só o áudio** (MP3, WAV, FLAC, OGG, M4A) |

¹ Precisa do programa gratuito **LibreOffice** instalado (veja [Programas opcionais](#programas-opcionais)).
² Precisa do programa gratuito **FFmpeg** instalado (veja [Programas opcionais](#programas-opcionais)).

**No modo JUNTAR** entram PDF, PNG, JPG, WEBP, BMP, TIFF, GIF e TXT — e também DOCX e XLSX, se o LibreOffice estiver instalado.

**No modo ORGANIZAR** entram arquivos PDF.

---

## Instalação

### Com o instalador (recomendado)

1. Dê um duplo clique no instalador **`FileMorph-<versão>-setup.exe`**.
2. Siga as etapas do instalador. Não é preciso ser administrador do computador, e **não é preciso ter Python instalado**: tudo o que o FileMorph usa vem dentro dele.
3. Pronto: o FileMorph aparece no **Menu Iniciar** (e na **Área de Trabalho**, se você marcar essa opção).

> O Windows pode mostrar o aviso "O Windows protegeu o computador", porque o
> instalador não tem assinatura digital. Clique em **Mais informações** e depois
> em **Executar assim mesmo**.

**Conferindo o arquivo baixado.** Junto do instalador vem um arquivo
`FileMorph-<versão>-setup.exe.sha256`. Para confirmar que o instalador chegou
inteiro, abra o PowerShell na pasta dele e rode
`Get-FileHash .\FileMorph-<versão>-setup.exe -Algorithm SHA256`: o código que
aparece precisa ser igual ao do arquivo `.sha256`.

### Versão portátil (sem instalar)

Se você não pode instalar programas, use **`FileMorph-<versão>-portable.exe`**:
é um arquivo só, que abre com duplo clique.

- Ele **demora alguns segundos a mais para abrir** que a versão instalada, porque
  a cada abertura descompacta o aplicativo numa pasta temporária.
- Não cria atalhos nem aparece em Configurações → Aplicativos: para "desinstalar",
  basta apagar o arquivo.
- As configurações ficam no mesmo lugar da versão instalada
  (`%APPDATA%\FileMorph`), e não ao lado do arquivo.

### Programas opcionais

O FileMorph funciona sozinho para imagens, PDF, textos, documentos e planilhas.
Duas funções dependem de programas gratuitos, que você instala só se precisar:

| Programa | Para que serve | Onde baixar |
|---|---|---|
| **FFmpeg** | Converter **áudio e vídeo** e tirar o áudio de um vídeo | [ffmpeg.org](https://ffmpeg.org/download.html) — depois de baixar, descompacte e adicione a pasta `bin` ao PATH do Windows |
| **LibreOffice** | Transformar **DOCX e XLSX em PDF** e usá-los no modo **Juntar** | [libreoffice.org](https://www.libreoffice.org/download/download-libreoffice/) — o FileMorph o encontra sozinho |

Depois de instalar um deles, **feche e abra o FileMorph de novo**.

Para ver o que está disponível no seu computador, clique no botão **⋯** (canto
superior direito) e em **Diagnóstico e dependências**. A janela mostra o que cada
programa habilita, tem um botão para a página oficial de download do que estiver
faltando e um botão **Copiar informações**, útil para pedir ajuda. O FileMorph
nunca baixa nem instala nada sozinho.

---

## Passo a passo básico

1. **Abra o FileMorph.**
2. **Adicione os arquivos**: arraste-os para a área tracejada no centro da janela, ou clique nela para escolher os arquivos.
3. **Escolha o modo** no topo: **CONVERTER**, **JUNTAR** ou **ORGANIZAR**.
4. **Complete a escolha**: no modo Converter, selecione o formato em **"Converter para"**.
5. **Clique no botão grande** na parte de baixo da janela.
6. **Acompanhe o progresso.** Se mudar de ideia, clique em **Cancelar**.
7. **Pronto!** Uma mensagem mostra onde o resultado foi salvo, com um botão **Abrir pasta** — e, se preferir, a pasta abre sozinha.

---

## Conhecendo a tela principal

De cima para baixo:

- **Cabeçalho** — o botão **⚙** abre as Configurações; o botão **⋯** tem as opções Configurações, Diagnóstico e dependências, Abrir pasta de logs, Ajuda e Sobre (que mostra a versão instalada).
- **Seletor de modo** — CONVERTER, JUNTAR e ORGANIZAR.
- **Área de arrastar** — onde você solta os arquivos (ou clica para escolher). O mascote fica aqui e reage ao que está acontecendo.
- **Lista de arquivos** — cada arquivo aparece com nome, tipo, tamanho e situação:
  `aguardando`, `processando`, `concluído`, `erro` (com o motivo logo abaixo) ou `cancelado`.
  O **×** tira um arquivo da lista, e **Limpar tudo** esvazia a lista. Tirar da lista não apaga o arquivo do computador.
- **Cartão de opções** — no modo Converter, a escolha do formato; no modo Organizar, qual PDF será organizado. Logo abaixo, quando algum arquivo da lista precisa de um programa que não está instalado (um MP3 sem FFmpeg, um DOCX que não vira PDF sem LibreOffice), uma linha avisa o que falta.
- **Botão principal** — CONVERTER ARQUIVOS, JUNTAR ARQUIVOS ou ORGANIZAR PÁGINAS. Ele fica apagado enquanto a operação não é possível; pare o mouse sobre ele para ver o motivo.

---

## Como usar cada funcionalidade

### Converter arquivos

1. Adicione um ou mais arquivos.
2. Deixe o modo **CONVERTER** selecionado.
3. Em **"Converter para"**, escolha o formato.
4. Clique em **CONVERTER ARQUIVOS**.

O que é bom saber:

- **Arquivos de tipos diferentes na mesma lista:** o seletor só mostra os formatos que servem para **todos** eles. Ex.: com uma foto PNG e um PDF, as opções são PNG, JPG, WEBP, BMP, TIFF e GIF.
- **O nome é mantido**, só muda a extensão: `ferias.jpg` vira `ferias.png`.
- **Já existe um arquivo com esse nome?** O FileMorph pergunta se deve **Substituir** ou **Criar cópia** (que ganha um número: `ferias (1).png`).
- **Arquivos com o mesmo nome, de pastas diferentes**, nunca gravam um por cima do outro: `C:\A\foto.jpg` e `C:\B\foto.png` convertidos para WEBP viram `foto.webp` e `foto (1).webp` — inclusive quando são convertidos ao mesmo tempo.
- **Um arquivo da própria lista nunca é substituído**, nem se você escolher "Substituir": o resultado vira uma cópia numerada.
- **PDF com várias páginas → imagens:** as imagens vão para uma pasta com o nome do PDF, uma por página (`relatorio/relatorio_p01.png`, `relatorio_p02.png`...).
- **TIFF com várias páginas** (comum em digitalizações): para PNG, JPG, WEBP, BMP ou GIF, funciona como o PDF — uma pasta com uma imagem por página. Para TIFF, continua um arquivo só, com todas as páginas. Para PDF, vira um PDF com todas as páginas.
- **GIF animado:** continua animado se o destino for GIF ou WEBP. Nos outros formatos (e no PDF), fica só o primeiro quadro.
- **Planilha com várias abas → CSV:** vira uma pasta com um CSV por aba — inclusive as abas ocultas.

### Juntar arquivos em um PDF

1. Adicione **dois ou mais** arquivos, **na ordem em que devem aparecer** no PDF final.
2. Selecione o modo **JUNTAR**.
3. Clique em **JUNTAR ARQUIVOS**.
4. Escolha o nome e o local do PDF final (a sugestão é `documento_final.pdf`) e confirme.

O que é bom saber:

- **A ordem da lista é a ordem do PDF final.** Os arquivos entram na ordem em que foram adicionados.
  Para acertar a ordem depois, use o modo **Organizar** no PDF gerado.
- Pode misturar tipos: PDF, imagens e textos no mesmo documento — e DOCX e XLSX, com o LibreOffice instalado.
- Um TIFF de várias páginas entra com todas elas; um GIF animado entra só com o primeiro quadro.
- PDFs protegidos por senha não podem ser juntados.
- O PDF final **não pode ter o nome de um dos arquivos que estão sendo juntados** (ele seria substituído). Se você escolher um desses nomes, o FileMorph pede outro.

### Organizar as páginas de um PDF

Use para mudar a ordem das páginas de um PDF — por exemplo, colocar a última
página no começo, ou corrigir um documento digitalizado fora de ordem.

**1. Abra a janela de organização**

1. Deixe **apenas um PDF** na lista de arquivos.
2. Selecione o modo **ORGANIZAR**. O cartão mostra: *"Organizar as páginas de: relatorio.pdf"*.
3. Clique em **ORGANIZAR PÁGINAS**.

**2. Entenda cada página**

Cada página aparece como um cartão com a miniatura e dois números:

- **O número em destaque**, no canto da miniatura, é a **posição da página no arquivo novo**. Ele muda enquanto você reorganiza.
- **"Página 3"**, embaixo, é o **número da página no PDF original**. Ele acompanha a página e fica colorido quando ela sai do lugar — assim você vê de relance o que mudou.

**3. Mude a ordem**

- **Arraste e solte** uma página no lugar desejado. Uma barra colorida mostra onde ela vai entrar.
  Soltar na metade esquerda de um cartão coloca a página antes dele; na metade direita, depois.
- **Várias páginas de uma vez:** selecione com **Ctrl** (uma a uma) ou **Shift** (um intervalo) e arraste qualquer uma delas. Elas vão juntas, na mesma ordem.
- **Documentos grandes:** ao arrastar perto da borda de cima ou de baixo, a lista rola sozinha.
  Ou use os botões de **Mover seleção** — para o início, uma posição para trás, uma para a frente, para o fim — ou os atalhos **Ctrl+Home**, **Ctrl+←**, **Ctrl+→** e **Ctrl+End**.

**4. Confira antes de salvar**

- Logo abaixo das páginas, a linha **"Nova ordem"** resume o resultado. Ex.: *Nova ordem: 3, 1, 4, 2*.
  Sequências longas aparecem resumidas: *50, 1–49, 51–100*.
- **Restaurar ordem original** desfaz tudo e volta ao começo.
- **Cancelar** fecha a janela sem salvar. Se você já tiver mudado a ordem, o FileMorph pergunta antes de descartar.

**5. Salve**

1. Clique em **Salvar PDF com a nova ordem**.
2. Escolha o nome e o local. A sugestão é o nome do original com `_reorganizado` no final (ex.: `relatorio_reorganizado.pdf`).
3. Acompanhe a barra de progresso. No fim, uma mensagem mostra onde o PDF foi salvo.

**O que o FileMorph garante na organização:**

- Nenhuma página é duplicada nem perdida — o arquivo novo tem exatamente as mesmas páginas.
- A qualidade é a original: as páginas não são convertidas em imagem nem recomprimidas.
- Marcadores (índice lateral) e links internos do PDF acompanham as páginas.
- O PDF original continua exatamente como estava.

---

## Exemplos rápidos

**Converter fotos do celular para PNG**
Arraste as fotos JPG → modo **CONVERTER** → "Converter para" **PNG** → **CONVERTER ARQUIVOS**.

**Transformar um PDF em imagens**
Arraste o PDF → modo **CONVERTER** → **JPG** → **CONVERTER ARQUIVOS**. Um PDF de 5 páginas vira uma pasta com 5 imagens.

**Montar um documento único para enviar**
Arraste, nesta ordem, `contrato.pdf`, `rg.jpg` e `comprovante.png` → modo **JUNTAR** → **JUNTAR ARQUIVOS** → salve como `processo.pdf`.

**Transformar uma digitalização TIFF em PDF**
Arraste o arquivo TIFF → modo **CONVERTER** → **PDF** → **CONVERTER ARQUIVOS**. Um TIFF de 10 páginas vira um PDF de 10 páginas.

**Reorganizar as páginas de um PDF**
Um PDF tem as páginas **1, 2, 3, 4** e você quer **3, 1, 4, 2**:

1. Modo **ORGANIZAR** → **ORGANIZAR PÁGINAS**.
2. Arraste a **página 3** para antes da página 1. Ordem: 3, 1, 2, 4.
3. Arraste a **página 4** para antes da página 2. Ordem: 3, 1, 4, 2.
4. Confira *"Nova ordem: 3, 1, 4, 2"* e clique em **Salvar PDF com a nova ordem**.

**Tirar só o áudio de um vídeo** *(precisa do FFmpeg)*
Arraste o vídeo MP4 → modo **CONVERTER** → **MP3** → **CONVERTER ARQUIVOS**.

**Abrir um CSV no Excel com as colunas certas**
Arraste o CSV → **CONVERTER** → **XLSX** → **CONVERTER ARQUIVOS**. Códigos com zero à esquerda, como CEP, continuam intactos.

---

## Configurações

Clique no botão **⚙** no canto superior direito.

| Opção | O que faz |
|---|---|
| **Pasta padrão** | Onde os arquivos convertidos são salvos. |
| **Abrir pasta após concluir** | Abre a pasta do resultado quando a operação termina. |
| **Mostrar mensagens do mascote** | Mostra ou esconde as falas do mascote. |
| **Animar o mascote** | Liga ou desliga os movimentos do mascote. |
| **Perguntar antes de substituir arquivos** | Se desligado, arquivos com o mesmo nome são substituídos sem perguntar. |
| **Processos simultâneos** | Quantos arquivos são convertidos ao mesmo tempo (de 1 a 8). Números maiores terminam lotes mais rápido, mas usam mais o computador. |
| **Tema** | A aparência da janela: clara ou escura. |

Se o arquivo de configurações for estragado (editado à mão com um valor errado,
por exemplo), só a opção com problema volta ao valor padrão — as outras continuam
como você deixou.

---

## Onde ficam os arquivos gerados

| Operação | Onde o resultado é salvo |
|---|---|
| **Converter** | Na **pasta padrão** — inicialmente `Documentos\FileMorph\Convertidos`. |
| **Juntar** | No nome e local que você escolher ao clicar em Juntar. |
| **Organizar** | No nome e local que você escolher ao salvar. |

---

## Informações importantes e limitações

**Sobre os seus arquivos**

- O original **nunca** é alterado nem apagado.
- Ao cancelar, nada fica pela metade: o que estava sendo gravado é descartado, e um arquivo que já existia com aquele nome continua intacto.
- Tudo acontece no seu computador: nenhum arquivo é enviado para a internet.

**Imagens**

- Fotos de celular que aparecem "deitadas" são giradas de verdade no arquivo novo, e a informação de giro sai dos dados da foto — assim ela não é girada duas vezes em outros programas. Data, câmera e localização da foto são mantidas nos formatos JPG e WEBP.
- **BMP** não tem transparência: as áreas transparentes de um PNG viram fundo branco (o mesmo acontece no JPG).
- **GIF** tem no máximo 256 cores, então fotos perdem um pouco de qualidade, e um pixel só pode ser totalmente transparente ou totalmente opaco: sombras e bordas suaves de um PNG recortado ficam serrilhadas.
- **TIFF** é gravado com compressão sem perda (LZW), mas sem os dados da foto (data, câmera e localização).

**PDF**

- PDFs **protegidos por senha**, ou com **proteção contra alterações** definida pelo autor, não podem ser organizados nem juntados. Remova a proteção antes.
- Se o PDF tiver **assinatura digital**, ela não continua válida no arquivo reorganizado — qualquer alteração em um documento assinado invalida a assinatura. O original, com a assinatura, fica guardado como estava.
- **PDF para imagem** usa 150 dpi, boa resolução para ver na tela. Páginas enormes (plantas, banners) saem com resolução menor, para caber na memória e no limite do formato escolhido — a página sai inteira, nunca cortada.
- **PDF para TXT** só funciona com PDFs que têm texto. Um documento **digitalizado** é uma foto da página e não tem texto por dentro; o FileMorph não faz reconhecimento de texto (OCR).
- Se a miniatura de alguma página não puder ser mostrada, o cartão exibe "sem prévia" — a página continua no documento normalmente.

**Documentos e planilhas**

- Converter para **TXT** guarda só o texto: negrito, cores, imagens e formatação não cabem em um arquivo de texto.
- Um **TXT para PDF** sai em página A4, com fonte de largura fixa. Travessões e aspas "curvas" viram os equivalentes simples (`--` e `"`).
- O **CSV** é gravado do jeito que o Excel em português espera (separado por ponto e vírgula), para abrir com as colunas certas.
- Vindo de um CSV, só vira número o que é claramente número: CEPs, códigos com zero à esquerda e datas continuam como texto, para não serem alterados.
- Ao converter uma planilha para CSV, células com **fórmula** viram o último valor calculado pelo Excel.

**Áudio e vídeo**

- Converter vídeo é demorado: leva mais ou menos o tempo de duração do próprio vídeo. O WEBM é o mais lento.
- As informações da música (título, artista, álbum) são mantidas; a capa do álbum não.

---

## Dúvidas comuns

**Aparece "Nenhum formato disponível ainda". Por quê?**
Não existe uma conversão que sirva para todos os arquivos da lista. Isso acontece com tipos que não combinam (ex.: um vídeo e uma planilha juntos) ou com áudio e vídeo sem o FFmpeg instalado.

**O botão principal está apagado.**
Pare o mouse sobre ele para ver o motivo. Os mais comuns: a lista está vazia; no modo Juntar há só um arquivo; no modo Organizar há mais de um arquivo na lista ou o arquivo não é PDF.

**As opções de áudio e vídeo não aparecem.**
Instale o FFmpeg, feche e abra o FileMorph. Confira em **⋯ → Diagnóstico e dependências**.

**Não aparece a opção PDF para o meu DOCX ou XLSX.**
Essa conversão precisa do LibreOffice. Instale-o, feche e abra o FileMorph.

**Onde está o arquivo que eu converti?**
Na pasta padrão, que você vê e muda em **⚙ Configurações** (inicialmente `Documentos\FileMorph\Convertidos`). A mensagem do fim da operação também mostra o local.

**Um arquivo deu erro. O que faço?**
O motivo aparece logo abaixo do nome, na lista. Se não for suficiente, a opção **⋯ → Abrir pasta de logs** mostra o registro técnico, e **⋯ → Diagnóstico e dependências → Copiar informações** copia a versão do FileMorph, do Windows e dos programas opcionais — útil para quem for ajudar.

**Posso abrir o FileMorph duas vezes?**
Pode. Cada janela usa os próprios arquivos temporários, e uma não atrapalha a conversão da outra.

**Posso continuar usando o computador enquanto o FileMorph trabalha?**
Sim. A janela continua respondendo, e o botão **Cancelar** funciona a qualquer momento.

---

## Desinstalar

Abra **Configurações do Windows → Aplicativos → FileMorph → Desinstalar**.

Suas configurações e os arquivos que você já converteu **não** são apagados.
A versão portátil não se desinstala: basta apagar o arquivo.

---

## Para quem desenvolve o FileMorph

Requer Python 3.12 ou mais novo (64 bits para gerar o instalador).

```bash
python -m pip install -r requirements-dev.txt   # aplicativo + testes
python main.py                                  # abre o aplicativo
python -m pytest                                # toda a suíte
python -m pytest -m "not integration"           # só os testes unitários
```

Os testes nunca usam o FFmpeg ou o LibreOffice instalados na máquina (usam
programas de mentira, em `tests/`), nem as configurações de quem os roda: o
resultado é o mesmo em qualquer computador. As categorias estão em `pytest.ini`.

**Gerar a versão distribuída** (Windows, PowerShell):

```powershell
python -m pip install -r requirements-build.txt -r requirements-dev.txt -c constraints-release.txt
.\empacotar.ps1              # instalador: dist\installer\FileMorph-<versão>-setup.exe (+ .sha256)
.\empacotar.ps1 -Portatil    # também o portátil: dist\portable\FileMorph-<versão>-portable.exe
```

O script roda os testes unitários, empacota com o PyInstaller (`FileMorph.spec`),
confere que nada de desenvolvimento entrou no pacote, executa o próprio
`FileMorph.exe --smoke-test` (converte uma imagem, monta um PDF e abre a janela
sem usar o Python da máquina), monta o instalador com o Inno Setup 6 e calcula o
SHA-256. Qualquer etapa que falhe encerra com erro. **O arquivo para compartilhar
é o `setup.exe`**: o `FileMorph.exe` de `dist\FileMorph` depende da pasta ao lado
dele e não funciona sozinho.

O workflow `.github/workflows/build-windows.yml` faz o mesmo no GitHub a cada push,
e numa tag `vX.Y.Z` anexa os arquivos a uma release em rascunho.

A versão mora só em `app/version.py`. As licenças das bibliotecas distribuídas
estão em `THIRD_PARTY_LICENSES.md`; para incluir um FFmpeg no instalador, veja
`vendor/ffmpeg/LEIA-ME.md`. Os instaladores antigos, que rodavam o código-fonte
com um Python da máquina, estão em `dev/legacy/`.

Os detalhes técnicos de cada parte estão documentados no início de cada arquivo do código, em `app/`.
