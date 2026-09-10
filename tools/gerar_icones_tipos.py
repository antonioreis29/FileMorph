"""
Gera os ícones de tipo de arquivo em `assets/icons/filetypes/`.

Por que um gerador, e não vinte SVGs escritos à mão: os ícones são
todos a mesma folha com canto dobrado, mudando só a cor (pela
categoria) e o rótulo (a extensão). Escrever isso vinte vezes seria
vinte oportunidades de um ficar torto. Aqui a forma existe uma vez só.

Rodar isto é opcional — os SVGs já vêm versionados no repositório.
Ele serve para quando a paleta mudar ou uma extensão nova entrar em
`KNOWN_EXTENSIONS`:

    python tools/gerar_icones_tipos.py

Substituir um ícone específico por arte própria não exige rodar nada:
basta sobrescrever o `.svg` correspondente. Só não rode o gerador
depois, ou ele volta a escrever o padrão por cima.

Sobre as cores: cada uma é forte o bastante para ser lida tanto sobre
o fundo claro quanto sobre o escuro, porque o rótulo é branco sobre a
cor cheia — o ícone não depende do fundo da janela para ter contraste.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.core.file_validator import KNOWN_EXTENSIONS  # noqa: E402

DESTINO = RAIZ / "assets" / "icons" / "filetypes"

# Uma cor por categoria, mais a de reserva usada pelo ícone genérico.
CORES = {
    "imagem": "#2E9E6B",
    "pdf": "#D2453C",
    "documento": "#3B72D4",
    "audio": "#8A54C8",
    "video": "#E0761F",
    "planilha": "#1B8C7A",
    "generico": "#7A7A85",
}

# A dobra do canto é desenhada com um tom mais escuro da própria cor,
# aplicado como uma camada preta translúcida — assim uma cor nova não
# exige calcular a sua sombra à mão.
GABARITO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 60" width="48" height="60" role="img" aria-label="{rotulo_acessivel}">
  <title>{rotulo_acessivel}</title>
  <!-- Folha: canto superior direito recortado, onde entra a dobra. -->
  <path d="M6 0 h24 l18 18 v36 a6 6 0 0 1 -6 6 h-36 a6 6 0 0 1 -6 -6 v-48 a6 6 0 0 1 6 -6 z" fill="{cor}"/>
  <!-- Dobra do canto. -->
  <path d="M30 0 l18 18 h-18 z" fill="#000000" fill-opacity="0.28"/>
  <!-- Rótulo com a extensão. A família é a genérica "sans-serif", e
       não uma fonte concreta: assim o ícone sai igual em qualquer
       máquina, sem depender de a Segoe UI (ou outra) estar instalada.
       Quem quiser fixar uma fonte específica pode editar os .svg. -->
  <text x="24" y="45" font-family="sans-serif"
        font-size="{tamanho}" font-weight="700" fill="#FFFFFF"
        text-anchor="middle" letter-spacing="{espacamento}">{texto}</text>
</svg>
"""


def tamanho_da_fonte(texto: str) -> tuple[int, str]:
    """Corpo e espaçamento do rótulo, conforme o número de letras.

    Sem isto, "JPEG" transbordaria a folha na mesma medida em que
    "PNG" cabe folgado.
    """
    if len(texto) <= 3:
        return 15, "0.5"
    if len(texto) == 4:
        return 12, "0"
    return 10, "-0.3"


def montar_svg(extensao: str, categoria: str) -> str:
    texto = extensao.upper()
    tamanho, espacamento = tamanho_da_fonte(texto)
    return GABARITO.format(
        cor=CORES.get(categoria, CORES["generico"]),
        texto=texto,
        tamanho=tamanho,
        espacamento=espacamento,
        rotulo_acessivel=f"Arquivo {texto}",
    )


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)

    for extensao, categoria in sorted(KNOWN_EXTENSIONS.items()):
        (DESTINO / f"{extensao}.svg").write_text(
            montar_svg(extensao, categoria), encoding="utf-8"
        )

    # O genérico cobre o arquivo cuja extensão não está em
    # KNOWN_EXTENSIONS. Ele não leva rótulo: não há o que escrever.
    generico = GABARITO.format(
        cor=CORES["generico"],
        texto="",
        tamanho=15,
        espacamento="0",
        rotulo_acessivel="Arquivo",
    )
    (DESTINO / "generico.svg").write_text(generico, encoding="utf-8")

    print(f"{len(KNOWN_EXTENSIONS) + 1} icones gerados em {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
