"""
Transforma uma imagem qualquer no ícone do FileMorph.

    python tools/gerar_icone_de_imagem.py caminho/da/imagem.png

Grava `assets/icons/filemorph.ico`, que é o arquivo usado pelos atalhos
do Menu Iniciar e da Área de Trabalho criados pelo `install.ps1`.

É o irmão do `preparar_mascote.py`: mesma limpeza de fundo (a função é
importada de lá, não copiada), destino diferente. O `gerar_mascote.py`
também produz um `.ico`, mas a partir da pixel art que ele mesmo
desenha; este aqui parte de uma imagem trazida de fora.

**Por que um `.ico` e não um `.png`.** O Windows não aceita PNG como
ícone de atalho, e um `.ico` não é uma imagem só: é um pacote com
várias resoluções. O Explorer escolhe a que couber melhor em cada
contexto — 16 px na barra de tarefas, 256 px na visualização de ícones
grandes. Um `.ico` com uma resolução só ficaria borrado em todos os
outros tamanhos.

**Por que quadrado antes de redimensionar.** Um desenho mais largo que
alto, espremido para caber em 64x64, sairia deformado. Ele é centrado
numa tela quadrada transparente, preservando a proporção.

Depois de rodar isto, reinstale (`Instalar FileMorph.bat`) para os
atalhos passarem a usar o ícone novo — o `install.ps1` lê o arquivo no
momento em que cria o atalho.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tools.preparar_mascote import recortar, remover_fundo  # noqa: E402

DESTINO = RAIZ / "assets" / "icons" / "filemorph.ico"

# Os tamanhos que um .ico do Windows costuma carregar. 16 e 32 são os
# que mais aparecem (barra de tarefas, lista do Explorer); 256 é o da
# visualização em ícones extra grandes.
TAMANHOS = (16, 24, 32, 48, 64, 128, 256)


def em_tela_quadrada(imagem: Image.Image) -> Image.Image:
    """Centra o desenho numa tela quadrada e transparente."""
    lado = max(imagem.size)
    if imagem.size == (lado, lado):
        return imagem

    tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    tela.paste(
        imagem,
        ((lado - imagem.width) // 2, (lado - imagem.height) // 2),
    )
    return tela


def camada(quadrada: Image.Image, lado: int) -> Image.Image:
    """Uma resolução do ícone.

    A escolha da interpolação segue a mesma regra do `mascot.py`: se a
    origem é pixel art e o destino é um múltiplo inteiro dela, NEAREST
    mantém a borda dura do pixel. Fora desse caso, LANCZOS é o que
    reduz sem serrilhar.
    """
    if lado == quadrada.width:
        return quadrada
    if lado > quadrada.width and lado % quadrada.width == 0:
        return quadrada.resize((lado, lado), Image.NEAREST)
    return quadrada.resize((lado, lado), Image.LANCZOS)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print("Erro: informe o caminho da imagem de origem.")
        return 1

    origem = Path(sys.argv[1])
    if not origem.is_file():
        print(f"Erro: '{origem}' nao existe.")
        return 1

    with Image.open(origem) as imagem:
        formato = imagem.format
        tamanho_original = imagem.size
        limpa = recortar(remover_fundo(imagem))

    quadrada = em_tela_quadrada(limpa)
    camadas = [camada(quadrada, lado) for lado in TAMANHOS]

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    # O Pillow grava a imagem da chamada mais as de `append_images`; a
    # maior vai como principal por convenção.
    camadas[-1].save(
        DESTINO,
        format="ICO",
        sizes=[(c.width, c.height) for c in camadas],
        append_images=camadas[:-1],
    )

    print(f"Origem:  {origem.name}  ({tamanho_original[0]}x{tamanho_original[1]}, {formato})")
    print(f"Recorte: {limpa.size[0]}x{limpa.size[1]} -> quadrado de {quadrada.width}")
    print(f"Destino: {DESTINO}  ({', '.join(str(t) for t in TAMANHOS)} px)")
    print()
    print("Reinstale (Instalar FileMorph.bat) para os atalhos usarem o icone novo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
