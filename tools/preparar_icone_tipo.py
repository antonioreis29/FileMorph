"""
Prepara uma imagem para virar o ícone de um ou mais tipos de arquivo.

    python tools/preparar_icone_tipo.py sprite.webp pdf
    python tools/preparar_icone_tipo.py bola.png mp3 wav flac ogg m4a

Grava `assets/icons/filetypes/<extensao>.png` para cada extensão
informada. Esses arquivos têm prioridade sobre os `.svg` gerados por
`gerar_icones_tipos.py`, então basta rodar isto para trocar a arte —
nada de código muda, e apagar o PNG faz o SVG voltar a valer.

**O problema que isto resolve.** As artes chegam de qualquer jeito:
como JPEG sem transparência, ampliadas em 1200x1200 a partir de um
sprite de 18 pixels, ou numa grade que não bate com a das outras. Feito
à mão, cada uma exige decisões diferentes e o resultado sai
desalinhado — ícones de tamanhos distintos na mesma lista. Aqui a
sequência é sempre a mesma:

1. **Remover o fundo**, reaproveitando `preparar_mascote.py`. Cobre o
   caso do JPEG, em que o xadrez que representa transparência veio
   gravado como pixel de verdade.
2. **Descobrir a grade nativa.** Uma arte ampliada 30x não é uma imagem
   de 540 pixels: são 18 pixels de arte em blocos de 30. Reduzir sem
   saber disso borra tudo.
3. **Levar à grade padrão** de `GRADE_PADRAO`, para que todos os ícones
   tenham o mesmo tamanho aparente na lista.
4. **Centrar na tela** de `TELA`, o mesmo enquadramento para todos.

A grade é descoberta de dois jeitos, porque um só não basta. O primeiro
é exato — o maior divisor comum dos comprimentos das sequências de
pixels iguais — e funciona em PNG e WebP. Ele falha em JPEG, cuja
compressão suja os pixels dentro de cada bloco e quebra as sequências;
aí entra o segundo, por reconstrução: reduzir para N, ampliar de volta
e medir o erro, para cada N plausível. O N certo reconstrói o original
quase perfeitamente, e os errados não chegam perto.
"""

from __future__ import annotations

import sys
from functools import reduce
from math import gcd
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tools.preparar_mascote import recortar, remover_fundo  # noqa: E402

DESTINO = RAIZ / "assets" / "icons" / "filetypes"

# Lado da arte, em pixels. É o tamanho em que os sprites de Poké Ball
# do projeto foram desenhados, e o que faz todos os ícones ocuparem o
# mesmo espaço no card.
GRADE_PADRAO = 18

# Lado da tela transparente em volta. A folga impede que a arte encoste
# nas bordas do rótulo na interface.
TELA = 24

# Faixa de grades consideradas na busca por reconstrução. Larga o
# bastante para cobrir os tamanhos usuais de sprite, estreita o
# bastante para a busca ser instantânea.
GRADES_PLAUSIVEIS = range(8, 49)


def _comprimentos_de_sequencia(imagem: Image.Image) -> list[int]:
    """Comprimentos das sequências de pixels idênticos, linha a linha."""
    largura, altura = imagem.size
    pixels = imagem.load()
    saida: list[int] = []

    passo = max(1, altura // 60)
    for y in range(0, altura, passo):
        atual, contagem = pixels[0, y], 1
        for x in range(1, largura):
            if pixels[x, y] == atual:
                contagem += 1
            else:
                saida.append(contagem)
                atual, contagem = pixels[x, y], 1
        saida.append(contagem)
    return saida


def grade_por_sequencias(arte: Image.Image) -> int | None:
    """A grade nativa, quando a arte tem blocos exatos.

    Devolve None se as sequências não revelarem bloco nenhum — o que
    acontece sempre que a origem passou por JPEG.
    """
    horizontais = _comprimentos_de_sequencia(arte)
    verticais = _comprimentos_de_sequencia(arte.transpose(Image.ROTATE_90))
    bloco = reduce(gcd, horizontais + verticais)

    if bloco <= 1 or arte.width % bloco or arte.height % bloco:
        return None
    return arte.width // bloco


def grade_por_reconstrucao(arte: Image.Image) -> int:
    """A grade nativa, por tentativa e erro.

    Para cada tamanho candidato, reduz a arte a ele e amplia de volta
    ao tamanho original. Se o candidato for a grade real, a ida e volta
    reproduz o original quase exatamente, porque cada bloco era mesmo
    de uma cor só. Se não for, blocos são partidos ao meio e o erro
    dispara.

    **O menor bom candidato vence, não o melhor.** Escolher o de menor
    erro parece óbvio e está errado: todo múltiplo da grade real também
    a representa exatamente, e ainda captura parte do ruído da
    compressão, então o erro continua caindo conforme o candidato
    cresce. Numa arte de grade 18 medida assim, o 36 marcou 3,8 contra
    4,8 do 18 — e o 36 teria sido escolhido, dobrando a resolução sem
    ganho nenhum de informação. O que identifica a grade real é a
    *queda brusca*: os vizinhos de 18 ficaram acima de 17, quatro vezes
    pior.
    """
    referencia = arte.convert("RGB")
    erros: list[tuple[int, float]] = []

    for candidato in GRADES_PLAUSIVEIS:
        if candidato > arte.width:
            break
        reduzida = arte.resize((candidato, candidato), Image.BOX)
        voltou = reduzida.resize(arte.size, Image.NEAREST).convert("RGB")
        diferenca = ImageChops.difference(referencia, voltou).convert("L")
        erros.append((candidato, ImageStat.Stat(diferenca).mean[0]))

    if not erros:
        return GRADE_PADRAO

    menor_erro = min(erro for _, erro in erros)

    # A margem multiplicativa acomoda o ruído que só um candidato maior
    # consegue absorver. A parcela fixa existe para o caso de uma arte
    # sem compressão, em que o candidato certo marca erro zero e
    # qualquer margem proporcional continuaria valendo zero.
    limiar = max(menor_erro * 1.5, 1.0)

    for candidato, erro in erros:
        if erro <= limiar:
            return candidato

    return GRADE_PADRAO


def para_grade(arte: Image.Image, destino: int) -> Image.Image:
    """Leva a arte a `destino` pixels de lado, do jeito menos destrutivo.

    Três casos, em ordem de preferência:

    - Já está no tamanho: nada a fazer.
    - O tamanho atual é múltiplo inteiro do destino: uma redução por
      vizinho mais próximo pega exatamente um pixel de cada bloco
      uniforme, sem inventar cor nenhuma.
    - Caso geral: supersampling alinhado à grade. Amplia por fator
      inteiro até o mínimo múltiplo comum dos dois tamanhos e só então
      reduz por fator inteiro, de modo que cada pixel de saída seja a
      média exata de um bloco. Reduzir direto de 20 para 18 faria o
      Pillow descartar duas linhas e duas colunas escolhidas
      arbitrariamente, quebrando o contorno de um jeito bem visível.
    """
    atual = arte.width
    if atual == destino:
        return arte

    if atual > destino and atual % destino == 0:
        return arte.resize((destino, destino), Image.NEAREST)

    comum = atual * destino // gcd(atual, destino)
    ampliada = arte.resize((comum, comum), Image.NEAREST)
    return ampliada.resize((destino, destino), Image.BOX)


def preparar(origem: Path) -> tuple[Image.Image, dict[str, object]]:
    """A imagem pronta para virar ícone, mais o que aconteceu no caminho."""
    with Image.open(origem) as imagem:
        formato = imagem.format
        tamanho_original = imagem.size
        limpa = recortar(remover_fundo(imagem))

    # Procurar grade só faz sentido numa arte ampliada. Uma que já
    # chega pequena está na resolução nativa por definição, e submetê-la
    # à busca é convidar o erro: num sprite de 18x18 vindo de WebP, o
    # candidato 17 marcou erro baixo o bastante para ser aceito, e a
    # arte seria reamostrada de 17 para 18 — degradada para nada. O
    # corte em duas vezes a grade padrão separa os dois mundos com
    # folga.
    if limpa.width < GRADE_PADRAO * 2:
        grade = limpa.width
        metodo = "tamanho nativo (arte nao ampliada)"
    else:
        grade = grade_por_sequencias(limpa)
        metodo = "sequencias exatas"
        if grade is None:
            grade = grade_por_reconstrucao(limpa)
            metodo = "reconstrucao (origem comprimida)"

    arte = limpa if limpa.width == grade else limpa.resize((grade, grade), Image.BOX)
    arte = para_grade(arte, GRADE_PADRAO)

    # O alfa fica fracionário depois de qualquer média, e uma borda
    # meio transparente vira um halo claro sobre o tema escuro.
    arte.putalpha(arte.getchannel("A").point(lambda v: 255 if v >= 128 else 0))

    tela = Image.new("RGBA", (TELA, TELA), (0, 0, 0, 0))
    tela.paste(arte, ((TELA - arte.width) // 2, (TELA - arte.height) // 2))

    return tela, {
        "formato": formato,
        "original": tamanho_original,
        "recorte": limpa.size,
        "grade": grade,
        "metodo": metodo,
    }


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        print("Erro: informe a imagem e ao menos uma extensao.")
        return 1

    origem = Path(sys.argv[1])
    extensoes = [e.lower().lstrip(".") for e in sys.argv[2:]]

    if not origem.is_file():
        print(f"Erro: '{origem}' nao existe.")
        return 1

    icone, info = preparar(origem)

    DESTINO.mkdir(parents=True, exist_ok=True)
    for extensao in extensoes:
        icone.save(DESTINO / f"{extensao}.png", format="PNG", optimize=True)

    print(f"Origem:  {origem.name}  ({info['original'][0]}x{info['original'][1]}, {info['formato']})")
    print(f"Recorte: {info['recorte'][0]}x{info['recorte'][1]}")
    print(f"Grade:   {info['grade']} -> {GRADE_PADRAO}  (detectada por {info['metodo']})")
    print(f"Destino: {TELA}x{TELA} em {DESTINO}")
    print(f"         {', '.join(f'{e}.png' for e in extensoes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
