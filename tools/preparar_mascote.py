"""
Prepara uma imagem qualquer para virar o mascote do FileMorph.

    python tools/preparar_mascote.py caminho/da/imagem.png

Grava o resultado em `assets/mascot/ditto.png`, que é o arquivo que a
janela carrega.

**O problema que isto resolve.** Imagens de pixel art baixadas da
internet quase sempre chegam de um destes dois jeitos ruins:

1. Salvas como JPEG (às vezes com extensão `.png`, o que engana), e
   JPEG não tem canal de transparência. O xadrez cinza-e-branco que o
   editor de imagem desenha para *representar* transparência acaba
   gravado como pixel de verdade.
2. Com fundo branco sólido.

Nos dois casos, colocar a imagem direto na janela mostra um retângulo
em volta do mascote — gritante no tema escuro.

**Como o fundo é removido.** Não por comparação de cor exata (a
compressão JPEG suja tudo), e sim por saturação: o fundo de um xadrez
ou de um branco liso é *cinza* — saturação baixa e claridade alta. O
contorno preto do desenho também tem saturação baixa, mas é escuro, e
por isso sobrevive ao teste. Depois, só viram transparentes os pixels
que estão *ligados à borda* da imagem, para não abrir buracos em áreas
claras dentro do próprio desenho.

Por fim a imagem é recortada no conteúdo, para o mascote ocupar todo o
espaço que recebe na interface em vez de flutuar com margem morta.
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.utils.resources import get_mascot_file  # noqa: E402

# Um pixel é "fundo" quando é lavado (pouca cor) e claro. Os limites
# são generosos de propósito: a compressão JPEG espalha os valores, e
# um xadrez que deveria ser cinza puro vira dezenas de tons próximos.
MAX_SATURACAO = 70
MIN_CLARIDADE = 140

# Passadas extras que comem a franja deixada pela compressão em volta do
# contorno. Sem isso sobra um halo cinza no recorte.
PASSADAS_DE_LIMPEZA = 2


def _e_fundo(pixel: tuple[int, int, int]) -> bool:
    r, g, b = pixel[:3]
    claridade = max(r, g, b)
    saturacao = claridade - min(r, g, b)
    return saturacao <= MAX_SATURACAO and claridade >= MIN_CLARIDADE


def remover_fundo(imagem: Image.Image) -> Image.Image:
    """Torna transparente o fundo ligado às bordas da imagem."""
    imagem = imagem.convert("RGBA")
    largura, altura = imagem.size
    pixels = imagem.load()

    transparente = [[False] * largura for _ in range(altura)]
    fila: deque[tuple[int, int]] = deque()

    def visitar(x: int, y: int) -> None:
        if transparente[y][x]:
            return
        if not _e_fundo(pixels[x, y]):
            return
        transparente[y][x] = True
        fila.append((x, y))

    # Semeia a busca com toda a moldura da imagem
    for x in range(largura):
        visitar(x, 0)
        visitar(x, altura - 1)
    for y in range(altura):
        visitar(0, y)
        visitar(largura - 1, y)

    while fila:
        x, y = fila.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < largura and 0 <= ny < altura:
                visitar(nx, ny)

    # Franja: pixels de fundo que encostam no que já ficou transparente
    for _ in range(PASSADAS_DE_LIMPEZA):
        novos = []
        for y in range(altura):
            for x in range(largura):
                if transparente[y][x] or not _e_fundo(pixels[x, y]):
                    continue
                vizinho_vazio = any(
                    transparente[y + dy][x + dx]
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= x + dx < largura and 0 <= y + dy < altura
                )
                if vizinho_vazio:
                    novos.append((x, y))
        if not novos:
            break
        for x, y in novos:
            transparente[y][x] = True

    for y in range(altura):
        for x in range(largura):
            if transparente[y][x]:
                pixels[x, y] = (0, 0, 0, 0)

    return imagem


def recortar(imagem: Image.Image) -> Image.Image:
    """Corta a margem transparente em volta do desenho."""
    caixa = imagem.getbbox()
    return imagem.crop(caixa) if caixa else imagem


def avisar_se_nao_for_o_escolhido(destino: Path) -> None:
    """Avisa quando o arquivo recém-gravado não é o que a janela vai usar.

    A janela prefere o `ditto.*` animado ao parado (ver
    `app/utils/resources.py`). Sem este aviso, gravar um `ditto.png` com
    um `ditto.gif` ao lado seria um comando que termina em "pronto" e
    não muda nada na tela — o pior tipo de silêncio.
    """
    escolhido = get_mascot_file()
    if escolhido is None or escolhido.resolve() == destino.resolve():
        return
    print()
    print(f"AVISO: a janela vai continuar usando '{escolhido.name}', que tem")
    print(f"       preferência sobre '{destino.name}'. Para usar o arquivo")
    print(f"       recém-gravado, tire '{escolhido.name}' da pasta.")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print("Erro: informe o caminho da imagem de origem.")
        return 1

    origem = Path(sys.argv[1])
    if not origem.is_file():
        print(f"Erro: '{origem}' não existe.")
        return 1

    destino = RAIZ / "assets" / "mascot" / "ditto.png"
    destino.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(origem) as imagem:
        formato = imagem.format
        original = imagem.size
        limpa = recortar(remover_fundo(imagem))

    limpa.save(destino, format="PNG", optimize=True)

    print(f"Origem:  {origem.name}  ({original[0]}x{original[1]}, {formato})")
    print(f"Destino: {destino}  ({limpa.size[0]}x{limpa.size[1]}, PNG com transparência)")
    avisar_se_nao_for_o_escolhido(destino)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
