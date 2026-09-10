# FileMorph

Aplicativo desktop para Windows que converte, transforma e junta arquivos
localmente — sem depender de sites diferentes para cada tipo de conversão.

**Conceito:** Arraste seus arquivos → escolha o formato → clique → pronto.

## Status atual do desenvolvimento

O desenvolvimento segue por fases, e cada fase só é marcada como pronta
quando existe de verdade no aplicativo:

- ✅ **FASE 1 — Estrutura**: arquitetura modular, configuração, logging.
- ✅ **FASE 2 — Interface**: janela principal, tema claro/escuro/sistema,
  drag and drop, lista de arquivos, seletor de operação, botão principal.
- ✅ **FASE 3 — Conversão de imagens**: PNG, JPG e WEBP em qualquer
  combinação, em lote, com progresso, cancelamento e relatório de erros
  por arquivo.
- ✅ **FASE 4 — PDF e junção**: imagens → PDF, PDF → imagens e o modo
  "Juntar", que une vários PDFs e imagens em um único PDF.
- ✅ **FASE 5 — fila de processamento real**: progresso de dentro das
  tarefas e cancelamento que interrompe a conversão já em andamento.
- ✅ **FASE 6 — áudio e vídeo** via FFmpeg: MP3, WAV, FLAC, OGG e M4A
  em qualquer combinação; MP4, MKV e WEBM entre si; e a extração da
  trilha sonora de um vídeo como arquivo de áudio.
- ⏳ **FASE 7 em diante** (documentos, mascote animado, build do
  executável) ainda **não foram implementadas**.

O princípio de projeto continua valendo: a interface só oferece
operações que existem de fato — não há botões ou opções "decorativas"
simulando funcionalidades inexistentes. Se você adicionar um DOCX, o
seletor de formato fica vazio e o botão principal desabilitado, porque
ainda não existe conversor registrado para esse formato. O mesmo vale
para um MP4 em uma máquina sem FFmpeg instalado.

### O que a Fase 3 já faz

- Converte imagens **PNG ↔ JPG ↔ WEBP**, uma ou várias de uma vez.
- Transparência vira fundo branco ao gerar JPG (que não tem canal alfa),
  em vez de falhar ou produzir cores erradas.
- Preserva metadados EXIF e perfil de cor ICC quando o formato de destino
  suporta, e aplica a rotação EXIF aos pixels para a foto não sair deitada.
- **Nunca altera o arquivo original.** Converter PNG para PNG na mesma
  pasta gera uma cópia numerada em vez de gravar por cima da origem.
- Se o arquivo de destino já existe, pergunta o que fazer:
  *Substituir*, *Criar cópia* ou *Cancelar* (respeitando a opção
  "confirmar substituição" nas configurações).
- Um arquivo corrompido no meio do lote não interrompe os demais: cada
  arquivo recebe seu próprio status (`concluído` / `erro` + motivo) na
  lista, e um resumo aparece ao final.
- A gravação é atômica: uma falha no meio da conversão não deixa arquivo
  truncado nem destrói um arquivo bom que já ocupasse aquele nome.

### O que a Fase 4 acrescentou

**Converter, com PDF nos dois sentidos:**

- **Imagem → PDF**: cada imagem vira um PDF de uma página, do tamanho
  exato da imagem (o DPI declarado no arquivo é respeitado; na falta
  dele, assume-se 72 dpi, sem recortar nem redimensionar nada).
- **PDF → imagem** (PNG, JPG ou WEBP), rasterizando a 150 dpi. Um PDF de
  uma página vira exatamente o arquivo pedido; um PDF de várias páginas
  vira uma subpasta com o nome do documento
  (`relatorio/relatorio_p01.png`, `_p02`, ...), para não espalhar
  dezenas de arquivos soltos na pasta de saída. Rodar a conversão de
  novo cria uma pasta nova em vez de sobrescrever a anterior.
- PDF protegido por senha ou corrompido dá uma mensagem clara, em vez
  de erro técnico.

**Juntar (o modo que até aqui não fazia nada):**

- Vários PDFs e/ou imagens viram **um único PDF**, na ordem em que
  aparecem na lista (a ordem da lista é a ordem do documento final).
- Misturar os dois tipos funciona: cada imagem é convertida para uma
  página de PDF em uma pasta temporária, e os intermediários são
  apagados ao final — tenha a junção dado certo ou errado.
- O nome e o local do arquivo final são escolhidos na hora, em um
  diálogo do próprio Windows.

### O que a Fase 5 acrescentou

Até aqui, uma conversão era uma caixa-preta: a barra só andava quando um
arquivo inteiro terminava, e "Cancelar" apenas impedia que os arquivos
*seguintes* começassem. Um PDF de 200 páginas ficava em 0% por um bom
tempo e não tinha como ser interrompido.

- **Progresso de dentro da tarefa**: a barra avança página a página de
  um PDF e arquivo a arquivo de uma junção, então ela se move mesmo
  quando o lote tem um único item grande.
- **Cancelamento de verdade**: o botão "Cancelar" alcança a conversão
  que já está rodando. A parada é *cooperativa* — acontece no próximo
  ponto seguro (entre duas páginas, entre dois arquivos), nunca no meio
  de uma gravação.
- **Nada pela metade**: ao cancelar, as páginas já escritas são
  apagadas, a subpasta vazia é removida, os intermediários da junção são
  limpos e um arquivo que já existisse no destino continua intacto.
- Os arquivos interrompidos aparecem na lista como `cancelado` — não
  como erro, porque não foram um.

Por dentro, isso é um `TaskContext` (`app/core/task_context.py`) que a
fila entrega a cada tarefa: por ele a operação reporta o andamento e
pergunta se deve parar. O módulo é livre de Qt de propósito, para que os
conversores não dependam da interface.

### O que a Fase 6 acrescentou

Áudio e vídeo, via **FFmpeg** — o primeiro conversor do FileMorph que
depende de um programa externo em vez de uma biblioteca Python.

- **Áudio**: MP3, WAV, FLAC, OGG e M4A em qualquer combinação. As tags
  (título, artista, álbum) são preservadas; a capa do álbum é
  descartada, porque formatos como o WAV não têm onde guardá-la e a
  conversão falharia por causa dela.
- **Vídeo**: MP4, MKV e WEBM entre si, além de AVI e MOV como origem.
  O resultado é H.264 + AAC (ou VP9 + Opus no WEBM), a combinação que
  toca em praticamente qualquer lugar.
- **Trilha sonora de um vídeo**: um MP4 também pode virar MP3, WAV,
  FLAC, OGG ou M4A, sem precisar de duas conversões em sequência.
- **Progresso contínuo**: a barra acompanha a duração já processada, e
  não etapas discretas — é o que faz um vídeo de dez minutos, que é uma
  tarefa só, mostrar que está andando.
- **Cancelamento real**: "Cancelar" encerra o processo do FFmpeg em
  andamento. Como a saída sempre vai para um arquivo temporário, o que
  já tinha sido escrito é descartado e um arquivo que já existisse no
  destino continua intacto.

**O aplicativo só oferece o que esta máquina consegue fazer.** A
verificação é dupla: se o FFmpeg não está instalado, os conversores de
mídia nem chegam a ser registrados e áudio/vídeo somem do seletor de
formato; se ele está instalado mas foi compilado sem algum codificador
(nem toda build traz `libvpx-vp9`, por exemplo), aquele formato
específico deixa de ser oferecido — em vez de aparecer no seletor e
falhar na hora de converter. O menu **"Verificar dependências"** mostra
exatamente o que está habilitado nesta instalação.

Vale o aviso: converter vídeo é recodificar quadro a quadro, e leva na
ordem de grandeza da duração do próprio vídeo — não os segundos de uma
imagem. O WEBM é o mais demorado dos três.

## Requisitos

- Windows 10/11 (desenvolvido e pensado para Windows, mas roda em
  qualquer SO com Python + PySide6 para fins de desenvolvimento).
- Python 3.12+
- PySide6 (interface), Pillow (imagens), pypdf (junção) e PyMuPDF
  (leitura de PDF) — todos instalados pelo `requirements.txt`. Cada um
  é verificado separadamente na inicialização: faltando um deles, o
  aplicativo abre normalmente e apenas as operações que dependiam
  daquela biblioteca deixam de ser oferecidas, com o motivo no log.
- **FFmpeg** (opcional, para áudio e vídeo): não é um pacote pip. Baixe
  em [ffmpeg.org](https://ffmpeg.org), descompacte e adicione a pasta
  `bin` ao PATH do Windows. Sem ele o FileMorph funciona normalmente
  para imagens e PDF.

## Instalação (para usar o aplicativo)

**Dê um duplo clique em `Instalar FileMorph.bat`**, na raiz do projeto.

O instalador de verdade é o `install.ps1` ao lado dele; o `.bat` existe
porque o Windows **não executa um `.ps1` com duplo clique**. Por
segurança, a extensão `.ps1` vem associada ao Bloco de Notas, então
clicar no `install.ps1` apenas abre o código como texto — o que costuma
parecer um defeito e não é. O `.bat` chama o PowerShell explicitamente e
manda ele rodar o script.

Se preferir o terminal, o efeito é o mesmo:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

O `-ExecutionPolicy Bypass` vale só para aquela execução e não altera a
política da máquina. Sem ele, a política padrão do Windows recusa o
script mesmo sendo um arquivo local.

A instalação copia o projeto para `%LOCALAPPDATA%\Programs\FileMorph`,
cria um ambiente virtual com as dependências e coloca atalhos no Menu
Iniciar e na Área de Trabalho.

O ícone dos atalhos é `assets/icons/filemorph.ico`. Para trocá-lo por
outra imagem:

```bash
python tools/gerar_icone_de_imagem.py caminho/da/imagem.png
```

A ferramenta remove o fundo, centra o desenho num quadrado e grava o
`.ico` com as sete resoluções que o Windows usa (de 16 a 256 px) — um
`.ico` de tamanho único ficaria borrado na barra de tarefas. Depois é
só reinstalar: o `install.ps1` lê o arquivo no momento em que cria o
atalho.

## Instalação (ambiente de desenvolvimento)

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

## Executando

Pelo terminal:

```bash
python main.py
```

Ou, sem terminal nenhum: **dê um duplo clique em `FileMorph.bat`**, na
raiz do projeto. Ele entra sozinho na pasta certa, usa o `.venv` se
existir (senão o `python`/`py` do sistema), instala as dependências na
primeira execução caso o PySide6 ou o Pillow ainda não estejam
disponíveis e abre a janela. Se algo der errado, a janela do console fica aberta explicando o
motivo em vez de sumir.

## Arquitetura

```
FileMorph/
├── main.py                  # ponto de entrada
├── tools/                   # utilitários de desenvolvimento, fora do app
│   ├── gerar_mascote.py     # desenha o mascote e o ícone (pixel art)
│   ├── gerar_icones_tipos.py # gera os ícones de tipo de arquivo (SVG)
│   ├── gerar_icone_de_imagem.py # vira o .ico do atalho a partir de
│   │                          uma imagem qualquer
│   └── preparar_mascote.py  # limpa o fundo de uma imagem trazida de fora
├── app/
│   ├── core/                # lógica central: conversão, junção, fila,
│   │                          validação — nada de UI aqui
│   ├── converters/          # um módulo por família de formato:
│   │                          image, pdf, audio e video implementados
│   │                          (media_converter.py é a base comum dos
│   │                          dois últimos); document e spreadsheet
│   │                          ainda são stubs
│   ├── mergers/             # um módulo por família de junção;
│   │                          pdf_merger.py implementado
│   ├── ui/                  # janelas e widgets PySide6
│   ├── utils/                # logging, arquivos temporários, ffmpeg,
│   │                          utilitários de arquivo
│   └── config/               # configurações persistidas do usuário
└── assets/                  # ícones, mascote, fontes
    └── icons/filetypes/     # o ícone que cada arquivo mostra na lista,
                               um arquivo por extensão. Um `<ext>.png`
                               colocado aqui substitui o `<ext>.svg`
                               gerado, sem apagar nada nem mexer no
                               código.
```

A UI nunca conversa diretamente com Pillow/pypdf/FFmpeg etc. Ela passa
por `app/core/processor.py`, que consulta a camada de compatibilidade
(`app/core/converter.py` / `app/core/merger.py`) para saber o que é
realmente possível, e delega a execução para o conversor/merger
registrado. `app/utils/ffmpeg_manager.py` é o único lugar do projeto
que cria um processo externo: é ele que detecta o FFmpeg, lista os
codificadores disponíveis, lê o andamento da conversão e traduz um erro
do FFmpeg em uma frase em português.

Quem preenche essa camada são `app/converters/__init__.py` e
`app/mergers/__init__.py`, chamados uma única vez no `main.py`. Eles só
registram um conversor/merger se a biblioteca dele estiver de fato
instalada — é assim que a interface continua honesta em uma máquina sem
Pillow ou sem PyMuPDF, por exemplo.

## Identidade visual e mascote

O tema tem três variantes (claro, escuro, sistema) e uma paleta só, em
`app/ui/styles.py`. As cores saem do mascote — são os tons do sprite —
com os papéis separados: **o rosa pastel é superfície** (fundos, área de
arrastar) e **o ameixa saturado é interação** (botões, progresso, foco).
O campo `on_accent` existe porque os dois temas discordam sobre o texto
em cima do destaque: branco no claro, ameixa no escuro, onde o botão é
rosa claro.

A arte é gerada por código, não editada em um programa de imagem:

```bash
python tools/gerar_mascote.py
```

Isso reescreve `assets/icons/filemorph.ico` (com 16, 32, 48, 64, 128 e
256 px) e `assets/mascot/ditto.png`. Silhueta, cores e rosto são números
no topo do script, então ajustar a arte é editar texto — e a diferença
entre duas versões aparece no diff. Os dois tamanhos pequenos são
desenhados em separado de propósito: reduzir a arte de 32 px pela metade
quebra o contorno, porque detalhe de um pixel não sobrevive à divisão.

**Trocando o mascote.** Nada disso é obrigatório. A janela usa
`assets/mascot/ditto.png` e, se ele não existir, a primeira imagem que
encontrar na pasta — então jogar um PNG ali dentro já funciona, com o
nome que for. O ícone do atalho é o que estiver em
`assets/icons/filemorph.ico`. Se a imagem sumir, o aplicativo abre
normalmente, apenas sem a figura.

Vale passar a imagem pelo preparador antes:

```bash
python tools/preparar_mascote.py caminho/da/imagem.png
```

Ele existe por um motivo prático. Pixel art baixada da internet quase
sempre vem salva como JPEG (às vezes com extensão `.png`, o que
engana), e JPEG não tem canal de transparência: o xadrez cinza que o
editor desenha para *representar* o fundo transparente acaba gravado
como pixel de verdade. Posta direto na janela, a imagem aparece com um
tabuleiro em volta — gritante no tema escuro. O preparador remove o
fundo por saturação (o xadrez é cinza; o contorno preto do desenho é
escuro e sobrevive ao teste), recorta a margem morta e grava um PNG com
transparência de verdade em `assets/mascot/ditto.png`.

## Configuração e logs

- Configurações do usuário: arquivo JSON em uma pasta de dados do
  aplicativo (`%APPDATA%/FileMorph` no Windows), gerenciado por
  `app/config/settings.py`.
- Logs técnicos: pasta `logs/` dentro da mesma pasta de dados,
  gerenciados por `app/utils/logger.py`. O usuário comum não precisa
  olhar esse arquivo — ele existe para diagnóstico.

## Testes

```bash
python -m pytest tests
```

A suíte cobre a camada de compatibilidade, a validação de arquivos, a
contabilidade da fila de tarefas, as conversões de imagem e de PDF, a
junção, as conversões de áudio/vídeo e o progresso/cancelamento — tudo
de verdade, gerando os arquivos na hora e conferindo o resultado
(inclusive a ordem das páginas do PDF final e o fato de que cancelar
não deixa sobras). Não depende de arquivos externos nem de rede.

A única exceção é o FFmpeg, que não é uma biblioteca Python: exigi-lo
instalado transformaria metade da suíte em "pulado" para quem só quer
rodar os testes. No lugar dele entra `tests/fake_ffmpeg.py`, um
programa que imita a parte do FFmpeg que o FileMorph usa de fato — ele
responde a `-encoders`, publica blocos de progresso e grava o arquivo
de saída. Assim o código exercitado é o de produção (leitura do
andamento, encerramento do processo, tradução do erro, gravação
atômica), e a única peça falsa é o binário do outro lado do cano.

## Próximos passos (Fase 7+)

Ver o prompt de desenvolvimento original para a ordem completa de
implementação. Resumidamente:

- **Fase 7 — documentos**: DOCX e TXT, possivelmente dependendo do
  LibreOffice em modo headless, o segundo binário externo do projeto.
- **Depois**: mascote animado e o build do executável.
- **Ainda em imagens**: BMP, TIFF e GIF, que ficaram fora da Fase 3 por
  exigirem tratamento próprio (paleta e animação).
- **Ainda em mídia**: opções de qualidade escolhidas pelo usuário
  (hoje cada formato tem um perfil fixo, pensado para o uso comum) e
  corte por trecho.
