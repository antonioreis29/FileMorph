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
- ⏳ **FASE 6 em diante** (áudio/vídeo, documentos, mascote animado,
  build do executável) ainda **não foram implementadas**.

O princípio de projeto continua valendo: a interface só oferece
operações que existem de fato — não há botões ou opções "decorativas"
simulando funcionalidades inexistentes. Se você adicionar um MP4 ou um
DOCX, o seletor de formato fica vazio e o botão principal desabilitado,
porque ainda não existe conversor registrado para esses formatos.

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

## Requisitos

- Windows 10/11 (desenvolvido e pensado para Windows, mas roda em
  qualquer SO com Python + PySide6 para fins de desenvolvimento).
- Python 3.12+
- PySide6 (interface), Pillow (imagens), pypdf (junção) e PyMuPDF
  (leitura de PDF) — todos instalados pelo `requirements.txt`. Cada um
  é verificado separadamente na inicialização: faltando um deles, o
  aplicativo abre normalmente e apenas as operações que dependiam
  daquela biblioteca deixam de ser oferecidas, com o motivo no log.

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
├── app/
│   ├── core/                # lógica central: conversão, junção, fila,
│   │                          validação — nada de UI aqui
│   ├── converters/          # um módulo por família de formato;
│   │                          image_converter.py e pdf_converter.py
│   │                          implementados, os demais são stubs
│   ├── mergers/             # um módulo por família de junção;
│   │                          pdf_merger.py implementado
│   ├── ui/                  # janelas e widgets PySide6
│   ├── utils/                # logging, arquivos temporários, ffmpeg,
│   │                          utilitários de arquivo
│   └── config/               # configurações persistidas do usuário
└── assets/                  # ícones, mascote, fontes
```

A UI nunca conversa diretamente com Pillow/pypdf/FFmpeg etc. Ela passa
por `app/core/processor.py`, que consulta a camada de compatibilidade
(`app/core/converter.py` / `app/core/merger.py`) para saber o que é
realmente possível, e delega a execução para o conversor/merger
registrado.

Quem preenche essa camada são `app/converters/__init__.py` e
`app/mergers/__init__.py`, chamados uma única vez no `main.py`. Eles só
registram um conversor/merger se a biblioteca dele estiver de fato
instalada — é assim que a interface continua honesta em uma máquina sem
Pillow ou sem PyMuPDF, por exemplo.

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
junção e o progresso/cancelamento — tudo de verdade, gerando os
arquivos na hora e conferindo o resultado (inclusive a ordem das
páginas do PDF final e o fato de que cancelar não deixa sobras). Não
depende de arquivos externos nem de rede.

## Próximos passos (Fase 6+)

Ver o prompt de desenvolvimento original para a ordem completa de
implementação. Resumidamente:

- **Fase 6 — áudio e vídeo** via FFmpeg, que já é detectado pelo menu
  "Verificar dependências". Será o primeiro conversor a depender de um
  binário externo, e o primeiro capaz de reportar progresso contínuo
  (percentual de duração), e não em etapas discretas.
- **Depois**: documentos, mascote animado e o build do executável.
- **Ainda em imagens**: BMP, TIFF e GIF, que ficaram fora da Fase 3 por
  exigirem tratamento próprio (paleta e animação).
