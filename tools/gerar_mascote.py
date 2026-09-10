"""
Gera os assets do mascote do FileMorph (pixel art) a partir de código.

Roda fora do aplicativo, à mão, quando a arte muda:

    python tools/gerar_mascote.py

Produz, dentro de `assets/`:

    icons/filemorph.ico   ícone do atalho, com todos os tamanhos
    mascot/ditto.png      mascote exibido na janela principal
    mascot/ditto_32.png   arte-mestra de 32px, para referência

A arte fica descrita como código (elipses, ondulações, coordenadas) em
vez de um binário opaco: assim dá para ajustar a silhueta ou a cor sem
abrir um editor de imagem, e a diferença entre duas versões aparece no
diff como texto.

**Dois tamanhos são desenhados à mão, não escalados.** Reduzir a arte de
32px para 16px pela metade quebra o contorno e transforma o rosto em
borrão — detalhes de um pixel simplesmente não sobrevivem à divisão. É
por isso que existe uma configuração separada para cada um, como se faz
em qualquer conjunto de ícones. Os tamanhos maiores, sim, são ampliações
por múltiplo inteiro da arte de 32px, o que preserva o pixel quadrado.

Nota sobre o mascote: o Ditto é um personagem da Nintendo/Game Freak. Os
desenhos aqui são originais, feitos para este projeto, e servem como
homenagem em uso pessoal. Se o FileMorph algum dia for distribuído
publicamente, o mascote deve ser trocado por arte própria.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

# --- Paleta do Ditto ---------------------------------------------------
# Tons de rosa-lilás com contorno ameixa: a leitura "Ditto" vem da
# combinação da cor com a silhueta amorfa e a boca ondulada.
OUTLINE = (74, 51, 80, 255)
BODY = (214, 160, 206, 255)
SHADOW = (170, 114, 161, 255)
HIGHLIGHT = (241, 205, 235, 255)
NADA = (0, 0, 0, 0)


@dataclass(frozen=True)
class Desenho:
    """Todos os números que definem uma versão da arte, em um lugar só."""

    size: int
    cx: float
    cy: float
    rx: float
    ry: float
    achatamento: float  # o quanto a base é mais reta que o topo
    espalhamento: float  # o quanto a base é mais larga que o topo
    ondulacoes: tuple[tuple[float, float, float], ...]  # (amplitude, freq, fase)
    olhos_x: tuple[int, int]
    olhos_y: int
    olho_largura: int
    olho_altura: int
    boca_x: tuple[int, int]
    boca_y: int
    boca_corrida: int
    brilho: tuple[float, float, float, float] | None  # cx, cy, rx, ry
    sombra: tuple[float, float] | None = None  # (limite_dy, limite_raio)


# Arte-mestra: 32px. É dela que saem 64, 128 e 256 por ampliação inteira.
MESTRA_32 = Desenho(
    size=32,
    cx=15.5,
    cy=16.5,
    rx=12.6,
    ry=11.0,
    achatamento=1.22,
    espalhamento=0.15,
    ondulacoes=((0.052, 3.0, 0.9), (0.030, 5.0, -1.7), (0.018, 2.0, 2.4)),
    olhos_x=(10, 20),
    olhos_y=13,
    olho_largura=2,
    olho_altura=3,
    boca_x=(9, 23),
    boca_y=19,
    boca_corrida=3,
    brilho=(10.2, 10.8, 3.9, 2.5),
    sombra=(0.44, 0.80),
)

# Versão de 16px: menos ondulação (num contorno curto ela vira serrilha),
# olhos de um pixel, boca de duas corridas e nada de sombra — em 16px a
# sombra só suja a silhueta em vez de dar volume.
MESTRA_16 = Desenho(
    size=16,
    cx=7.5,
    cy=8.45,
    rx=6.2,
    ry=5.25,
    achatamento=1.18,
    espalhamento=0.13,
    ondulacoes=((0.030, 3.0, 0.9),),
    olhos_x=(4, 10),
    olhos_y=5,
    olho_largura=1,
    olho_altura=2,
    boca_x=(5, 11),
    boca_y=9,
    boca_corrida=2,
    brilho=(4.6, 5.0, 2.0, 1.3),
    sombra=None,
)


def _dentro(d: Desenho, x: int, y: int) -> bool:
    """Silhueta: elipse larga com a base achatada e o contorno ondulado.

    A soma de ondulações em frequências diferentes é o que tira a cara
    de bola perfeita sem virar mancha aleatória.
    """
    dx = (x + 0.5 - d.cx) / d.rx
    dy = (y + 0.5 - d.cy) / d.ry

    # O Ditto não é uma bola: ele escorre. A base espalha mais que o
    # topo, o que dá a silhueta de gota achatada em vez de círculo.
    dx /= 1.0 + d.espalhamento * dy

    if dy > 0:
        dy *= d.achatamento

    angulo = math.atan2(dy, dx)
    fator = 1.0
    for amplitude, frequencia, fase in d.ondulacoes:
        fator += amplitude * math.sin(angulo * frequencia + fase)

    return (dx * dx + dy * dy) <= fator * fator


def _boca(d: Desenho, grade) -> None:
    """A onda larga e rasa que é a marca do Ditto.

    Duas lições das tentativas descartadas estão embutidas aqui.

    A primeira: um seno arredondado para a grade produz degraus de
    tamanhos irregulares, e o olho lê isso como um raio quebrado, não
    como uma onda. Pixel art resolve com corridas de comprimento igual
    alternando entre duas alturas — uma onda quadrada.

    A segunda: é preciso ligar verticalmente o fim de uma corrida ao
    começo da próxima. Sem essa ligação a boca vira uma fileira de
    tracinhos soltos.
    """
    x0, x1 = d.boca_x
    anterior: int | None = None

    for x in range(x0, x1):
        alto = ((x - x0) // d.boca_corrida) % 2 == 1
        y = d.boca_y + (1 if alto else 0)

        if anterior is not None and y != anterior:
            passo = 1 if y > anterior else -1
            for yy in range(anterior, y, passo):
                grade[yy][x] = OUTLINE

        grade[y][x] = OUTLINE
        anterior = y


def _elipse(d: Desenho, grade, cx, cy, rx, ry, cor) -> None:
    for y in range(d.size):
        for x in range(d.size):
            if grade[y][x] not in (BODY, SHADOW, HIGHLIGHT):
                continue
            ex = (x + 0.5 - cx) / rx
            ey = (y + 0.5 - cy) / ry
            if ex * ex + ey * ey <= 1.0:
                grade[y][x] = cor


def desenhar(d: Desenho) -> Image.Image:
    grade = [[NADA for _ in range(d.size)] for _ in range(d.size)]

    # 1) Corpo
    for y in range(d.size):
        for x in range(d.size):
            if _dentro(d, x, y):
                grade[y][x] = BODY

    # 2) Sombra, acompanhando a curva da base em vez de cortar reto
    if d.sombra is not None:
        limite_dy, limite_raio = d.sombra
        for y in range(d.size):
            for x in range(d.size):
                if grade[y][x] != BODY:
                    continue
                dx = (x + 0.5 - d.cx) / d.rx
                dy = (y + 0.5 - d.cy) / d.ry
                if dy > limite_dy and (dx * dx + (dy * 1.15) ** 2) > limite_raio:
                    grade[y][x] = SHADOW

    # 3) Brilho
    if d.brilho is not None:
        _elipse(d, grade, *d.brilho, HIGHLIGHT)

    # 4) Contorno: todo pixel vazio que encosta no corpo
    contorno = []
    for y in range(d.size):
        for x in range(d.size):
            if grade[y][x] != NADA:
                continue
            encosta = any(
                grade[y + dy][x + dx] != NADA
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= x + dx < d.size and 0 <= y + dy < d.size
            )
            if encosta:
                contorno.append((x, y))
    for x, y in contorno:
        grade[y][x] = OUTLINE

    # 5) Farpas: um pixel de contorno que quase não encosta em nada
    # aparece como sujeira na silhueta.
    farpas = []
    for y in range(d.size):
        for x in range(d.size):
            if grade[y][x] != OUTLINE:
                continue
            vizinhos = sum(
                1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= x + dx < d.size
                and 0 <= y + dy < d.size
                and grade[y + dy][x + dx] != NADA
            )
            if vizinhos <= 1:
                farpas.append((x, y))
    for x, y in farpas:
        grade[y][x] = NADA

    # 6) Olhos
    for ex in d.olhos_x:
        for dy in range(d.olho_altura):
            for dx in range(d.olho_largura):
                grade[d.olhos_y + dy][ex + dx] = OUTLINE

    # 7) Boca
    _boca(d, grade)

    imagem = Image.new("RGBA", (d.size, d.size), NADA)
    imagem.putdata([grade[y][x] for y in range(d.size) for x in range(d.size)])
    return imagem


def main() -> int:
    raiz = Path(__file__).resolve().parent.parent
    icones = raiz / "assets" / "icons"
    mascote = raiz / "assets" / "mascot"
    icones.mkdir(parents=True, exist_ok=True)
    mascote.mkdir(parents=True, exist_ok=True)

    arte32 = desenhar(MESTRA_32)
    arte16 = desenhar(MESTRA_16)

    # O .ico guarda vários tamanhos e o Windows escolhe o melhor para
    # cada contexto. Só entram ampliações por múltiplo inteiro (2x, 4x,
    # 8x), que mantêm o pixel quadrado e nítido; 48 vem do desenho de
    # 16 por isso mesmo (16 x 3), e não do de 32, que exigiria 1,5x.
    camadas = [
        arte16,
        arte16.resize((48, 48), Image.NEAREST),
        arte32,
        arte32.resize((64, 64), Image.NEAREST),
        arte32.resize((128, 128), Image.NEAREST),
        arte32.resize((256, 256), Image.NEAREST),
    ]
    destino_ico = icones / "filemorph.ico"
    camadas[-1].save(
        destino_ico,
        format="ICO",
        sizes=[(c.width, c.height) for c in camadas],
        append_images=camadas[:-1],
    )

    # Mascote da janela: 4x a arte-mestra, nítido em telas comuns e com
    # folga para telas de alta densidade.
    arte32.resize((128, 128), Image.NEAREST).save(mascote / "ditto.png")
    arte32.save(mascote / "ditto_32.png")

    print(f"Ícone:   {destino_ico}")
    print(f"Mascote: {mascote / 'ditto.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
