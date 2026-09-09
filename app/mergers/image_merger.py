"""
Junção de imagens — RESERVADO PARA UMA FASE FUTURA.

O caso mais comum ("várias imagens viram um PDF") foi implementado na
Fase 4 dentro de `pdf_merger.py`, e não aqui: um único merger cobrindo
PDFs, imagens e a mistura dos dois evita que dois mergers aceitem os
mesmos formatos e deixem o registro de compatibilidade ambíguo.

Este módulo fica reservado para a junção de imagem *em imagem* — a
colagem vertical/horizontal de várias imagens em um único arquivo PNG
ou JPG. Enquanto não existir de fato, nada é registrado e a interface
não oferece a operação (item 37).
"""

# from app.core.merger import BaseMerger, MergeResult
#
# class ImageCollageMerger(BaseMerger):
#     ...  # junção de imagens em uma única imagem (fase futura)
