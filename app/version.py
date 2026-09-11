"""
Versão do FileMorph, em um lugar só.

Existe porque a versão passou a ser lida de fora do Python: o
`install.ps1` a grava no registro do Windows (é o que aparece em
Configurações > Aplicativos), o `FileMorph.spec` a carimba nas
propriedades do `.exe`, e o `installer/FileMorph.iss` a usa no nome do
`setup.exe`. Com a constante espalhada, uma atualização esqueceria
algum desses lugares e o usuário veria versões diferentes conforme
onde olhasse.

Os scripts do instalador não importam este módulo — eles não têm um
Python garantido no momento em que rodam. Em vez disso leem esta linha
por expressão regular, e é por isso que ela deve continuar simples:
`__version__ = "x.y.z"`, aspas duplas, sem cálculo em volta.

O formato é `MAJOR.MINOR.PATCH`. O Windows exige que `DisplayVersion`
seja numérico neste formato, então sufixos como "1.0.0-beta" quebrariam
o registro.
"""

from __future__ import annotations

__version__ = "1.2.0"

# Nome exibido em todo lugar que o usuário vê: título da janela,
# Painel de Controle, atalhos.
APP_NAME = "FileMorph"

# Autor do aplicativo. Aparece na coluna "Publicador" do Painel de
# Controle; sem ele o Windows mostra a linha em branco.
APP_PUBLISHER = "Antonio Reis"

# Endereco do projeto, oferecido pelo Painel de Controle no link
# "Suporte".
APP_URL = "https://github.com/antonioreis29/FileMorph"
