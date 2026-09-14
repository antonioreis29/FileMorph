"""
Um LibreOffice de mentira, usado pelos testes de documento, planilha e junção.

Mesmo raciocínio do `fake_ffmpeg.py`: a suíte não pode exigir um
LibreOffice instalado na máquina que a roda — é um programa de centenas
de megabytes —, mas o conversor de DOCX para PDF tem lógica própria que
merece teste: montar a linha de comando certa, encontrar o arquivo que
o LibreOffice gravou, mover esse arquivo para o destino de forma atômica,
perceber que o processo terminou sem gravar nada, traduzir o erro e
obedecer ao cancelamento.

Este script imita o pedaço do `soffice` que o FileMorph usa de fato:
responde a `--version` e ao `--convert-to`, grava o arquivo de saída na
pasta indicada por `--outdir` usando o nome do documento de origem, e
imprime a linha de relatório no mesmo formato do original.

O PDF que ele grava é um PDF de verdade, feito com o PyMuPDF que o
projeto já usa. Isso é necessário porque a junção concatena o
resultado com os outros arquivos: um arquivo de mentira com a assinatura
certa passaria pelo conversor e quebraria no pypdf, e o teste diria que o
problema está na junção quando está no dublê.

Opções próprias, sempre antes dos argumentos do LibreOffice:

    --record CAMINHO    grava os argumentos recebidos, para o teste conferir
    --delay S           demora este tempo antes de gravar a saída
    --fail MENSAGEM     falha com esta mensagem, como um documento ilegível
    --silent 1          termina bem, mas sem gravar nada (o caso traiçoeiro)
    --width N           largura da página, para o teste identificar a ordem
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    delay = 0.0
    fail_message = None
    record_path = None
    silent = False
    width = 400.0

    # As opções próprias vêm todas juntas na frente, em pares.
    while argv and argv[0].startswith("--") and argv[0] in _OWN_OPTIONS:
        option, value, argv = argv[0], argv[1], argv[2:]
        if option == "--record":
            record_path = value
        elif option == "--delay":
            delay = float(value)
        elif option == "--fail":
            fail_message = value
        elif option == "--silent":
            silent = value == "1"
        elif option == "--width":
            width = float(value)

    if "--version" in argv:
        print("LibreOffice 9.9.9.9 fake(Build:1)")
        return 0

    # Só a conversão é registrada: o `--version` é consulta interna do
    # FileMorph, e gravá-la apagaria o que o teste quer ver.
    if record_path:
        Path(record_path).write_text(json.dumps(argv), encoding="utf-8")

    if delay:
        time.sleep(delay)

    if fail_message:
        print(fail_message, file=sys.stderr, flush=True)
        return 1

    source = Path(argv[-1])
    target_ext = _option_value(argv, "--convert-to") or "pdf"
    outdir = Path(_option_value(argv, "--outdir") or ".")

    if silent:
        # O LibreOffice de verdade faz isto com documento corrompido:
        # termina com código 0 e não grava nada. Sem esta possibilidade, o
        # teste não conseguiria provar que o FileMorph confere a saída.
        return 0

    produced = outdir / f"{source.stem}.{target_ext}"
    _write_pdf(produced, width)
    print(f"convert {source} -> {produced} using filter : writer_pdf_Export")
    return 0


_OWN_OPTIONS = ("--record", "--delay", "--fail", "--silent", "--width")


def _write_pdf(path: Path, width: float) -> None:
    """Um PDF de uma página, válido o suficiente para ser concatenado."""
    import pymupdf

    document = pymupdf.open()
    try:
        page = document.new_page(width=width, height=200)
        page.insert_text((20, 40), "documento convertido pelo fake_soffice")
        document.save(str(path))
    finally:
        document.close()


def _option_value(argv: list[str], name: str) -> str | None:
    if name not in argv:
        return None
    index = argv.index(name)
    return argv[index + 1] if index + 1 < len(argv) else None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
