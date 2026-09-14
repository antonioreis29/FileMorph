# Componentes de terceiros

O FileMorph distribuído (instalador e executável portátil) leva junto o
interpretador Python e as bibliotecas abaixo. Cada uma continua sob a sua
própria licença; este arquivo diz quais são e onde encontrar o texto
completo de cada uma.

As versões são as de `constraints-release.txt`, que é com o que o
instalador é montado.

| Componente | Versão | Licença | Para que o FileMorph usa |
|---|---|---|---|
| [Python](https://www.python.org/) | 3.13 | PSF License | O interpretador que roda o aplicativo |
| [PySide6 / Qt for Python](https://www.qt.io/qt-for-python) (PySide6-Essentials, PySide6-Addons, shiboken6) | 6.11.2 | LGPL-3.0 (ou GPL-2.0/GPL-3.0) | A interface |
| [Qt](https://www.qt.io/) (bibliotecas distribuídas dentro do PySide6) | 6.11 | LGPL-3.0 | A interface |
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU (HPND) | Imagens |
| [PyMuPDF](https://pymupdf.readthedocs.io/) | 1.28.2 | **AGPL-3.0** ou licença comercial da Artifex | PDF → imagens, TXT ↔ PDF, organização de páginas |
| [pypdf](https://pypdf.readthedocs.io/) | 6.18.0 | BSD-3-Clause | Junção de PDFs |
| [python-docx](https://python-docx.readthedocs.io/) | 1.2.0 | MIT | Documentos DOCX |
| [lxml](https://lxml.de/) | 6.1.3 | BSD-3-Clause | Leitura de DOCX (dependência do python-docx) |
| [typing_extensions](https://github.com/python/typing_extensions) | 4.16.0 | PSF-2.0 | Dependência do python-docx |
| [openpyxl](https://openpyxl.readthedocs.io/) | 3.1.5 | MIT | Planilhas XLSX |
| [et_xmlfile](https://foss.heptapod.net/openpyxl/et_xmlfile) | 2.0.0 | MIT | Dependência do openpyxl |
| [PyInstaller](https://pyinstaller.org/) (carregador do executável) | 6.22.2 | GPL-2.0 com exceção para o carregador | Monta o executável; o carregador que ele embute pode ser distribuído com qualquer licença |

Ferramentas usadas só para testar e empacotar (pytest, Inno Setup) não são
distribuídas.

## Atenção antes de distribuir

- **PyMuPDF é AGPL-3.0.** Distribuir um programa que o inclui obriga a
  oferecer o código-fonte do programa inteiro sob termos compatíveis com a
  AGPL — ou a ter uma licença comercial da Artifex. O código do FileMorph
  está em [github.com/antonioreis29/FileMorph](https://github.com/antonioreis29/FileMorph),
  mas o repositório ainda não declara uma licença. **Decida e declare a
  licença do projeto (compatível com a AGPL-3.0) antes de publicar o
  instalador**, ou troque a biblioteca.
- **PySide6/Qt são LGPL-3.0.** O instalador distribui as DLLs do Qt como
  arquivos separados (é o que o modo "pasta" do PyInstaller faz), o que
  permite ao usuário substituí-las — a condição principal da LGPL. O
  executável portátil empacota tudo num arquivo só; quem precisar trocar as
  bibliotecas deve usar a versão instalada.

## Programas externos opcionais

### FFmpeg

O aplicativo **não inclui** o FFmpeg nesta versão. Ele usa o FFmpeg
encontrado nesta ordem: o que vier em `vendor/ffmpeg` junto com o
FileMorph, um caminho definido nas configurações (`ffmpeg_path` no
`settings.json`), o PATH do Windows.

Para distribuir o FileMorph **com** o FFmpeg, a licença do build escolhido
precisa ser verificada e registrada aqui antes, e o arquivo de licença do
build precisa estar em `vendor/ffmpeg` (a receita do PyInstaller recusa
empacotar o FFmpeg sem ele). Veja `vendor/ffmpeg/LEIA-ME.md`. Registre nesta
seção, ao incluir:

| Campo | Valor |
|---|---|
| Build | *(nenhum incluído nesta versão)* |
| Origem (URL e data) | — |
| Versão | — |
| Licença (LGPL-2.1 ou GPL-3.0, conforme a compilação) | — |
| Onde está o código-fonte correspondente | — |

### LibreOffice

Não é distribuído. O usuário instala por conta própria, a partir da
[página oficial](https://www.libreoffice.org/download/download-libreoffice/),
se quiser converter DOCX e XLSX em PDF. O LibreOffice é MPL-2.0.
