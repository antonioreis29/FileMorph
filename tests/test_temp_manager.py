"""
Testes do gerenciador de temporários (`app/utils/temp_manager.py`).

O que está sendo protegido: uma execução do FileMorph nunca apaga os
temporários de outra que ainda está aberta, e o que sobra de uma execução
que terminou (inclusive derrubada) acaba sendo limpo.

Todos os testes usam uma raiz dentro da pasta temporária do próprio teste
— nunca o `%TEMP%\\FileMorph` real, onde um FileMorph aberto nesta máquina
poderia estar trabalhando.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from app.utils.temp_manager import LOCK_NAME, ROOT_NAME, TempManager

ROOT = Path(__file__).resolve().parent.parent


def _age(folder: Path, seconds: float) -> None:
    """Deixa a pasta e tudo dentro dela com cara de antigos."""
    past = time.time() - seconds
    for path in [folder, *folder.rglob("*")]:
        os.utime(path, (past, past))


def test_nothing_is_created_until_it_is_needed(tmp_path: Path) -> None:
    TempManager(tmp_path)

    assert not (tmp_path / ROOT_NAME).exists()


def test_each_instance_works_in_its_own_folder(tmp_path: Path) -> None:
    first, second = TempManager(tmp_path), TempManager(tmp_path)

    session_a = first.new_session()
    session_b = second.new_session()

    assert first.instance_dir != second.instance_dir
    assert first.session_dir(session_a).parent == first.instance_dir
    assert second.session_dir(session_b).parent == second.instance_dir
    assert first.instance_dir.parent == tmp_path / ROOT_NAME


def test_session_cleanup_removes_only_that_session(tmp_path: Path) -> None:
    manager = TempManager(tmp_path)
    keep, drop = manager.new_session(), manager.new_session()
    (manager.session_dir(drop) / "intermediario.pdf").write_bytes(b"x")

    manager.cleanup(drop)

    assert not manager.session_dir(drop).exists()
    assert manager.session_dir(keep).is_dir()


def test_closing_one_instance_never_touches_another(tmp_path: Path) -> None:
    """O defeito antigo: a segunda janela apagava a raiz inteira ao abrir, e
    com ela os arquivos que a primeira ainda estava usando."""
    busy, closing = TempManager(tmp_path), TempManager(tmp_path)
    in_use = busy.session_dir(busy.new_session()) / "pagina_em_uso.pdf"
    in_use.write_bytes(b"conversao em andamento")
    closing.new_session()
    closing_dir = closing.instance_dir

    closing.cleanup_own()
    TempManager(tmp_path).cleanup_orphans(min_age_seconds=0)  # uma terceira abrindo

    assert in_use.read_bytes() == b"conversao em andamento"
    assert not closing_dir.exists()


def test_starting_an_instance_never_removes_a_live_one_even_if_old(tmp_path: Path) -> None:
    """A trava de uma instância viva protege a pasta dela mesmo que nada
    tenha sido gravado há muito tempo."""
    live = TempManager(tmp_path)
    in_use = live.session_dir(live.new_session()) / "arquivo.pdf"
    in_use.write_bytes(b"x")
    _age(live.instance_dir, 10 * 24 * 3600)

    removed = TempManager(tmp_path).cleanup_orphans(min_age_seconds=0)

    assert live.instance_dir not in removed
    assert in_use.exists()


def test_folder_of_a_finished_instance_is_removed(tmp_path: Path) -> None:
    finished = TempManager(tmp_path)
    leftover = finished.session_dir(finished.new_session()) / "sobra.pdf"
    leftover.write_bytes(b"x")
    folder = finished.instance_dir
    # Simula o fim do processo: a trava é liberada, a pasta fica.
    finished._lock_handle.close()
    finished._lock_handle = None

    removed = TempManager(tmp_path).cleanup_orphans()

    assert removed == [folder]
    assert not folder.exists()


def test_a_crashed_instance_is_detected_by_its_released_lock(tmp_path: Path) -> None:
    """Um processo de verdade cria a pasta e morre sem limpar nada. A trava
    que ele segurava é liberada pelo sistema, e a pasta vira órfã."""
    script = textwrap.dedent(
        f"""
        import os, sys
        sys.path.insert(0, {str(ROOT)!r})
        from app.utils.temp_manager import TempManager
        manager = TempManager({str(tmp_path)!r})
        session = manager.session_dir(manager.new_session())
        (session / "sobra.pdf").write_bytes(b"x")
        print(manager.instance_dir, flush=True)
        os._exit(0)  # sem limpeza nenhuma, como uma queda
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0, completed.stderr
    crashed_dir = Path(completed.stdout.strip())
    assert crashed_dir.is_dir()

    removed = TempManager(tmp_path).cleanup_orphans()

    assert removed == [crashed_dir]


@pytest.mark.integration
def test_a_second_process_never_removes_the_folder_of_a_running_one(tmp_path: Path) -> None:
    """Duas instâncias de verdade, em dois processos: a que abre depois roda a
    limpeza de órfãos e a pasta da que continua aberta fica intacta."""
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from app.utils.temp_manager import TempManager
        manager = TempManager({str(tmp_path)!r})
        session = manager.session_dir(manager.new_session())
        (session / "em_uso.pdf").write_bytes(b"x")
        print(manager.instance_dir, flush=True)
        sys.stdin.readline()  # fica aberta até o teste mandar terminar
        manager.cleanup_own()
        """
    )
    running = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        running_dir = Path(running.stdout.readline().strip())
        assert running_dir.is_dir()

        removed = TempManager(tmp_path).cleanup_orphans(min_age_seconds=0)

        assert running_dir not in removed
        assert (running_dir / LOCK_NAME).exists()
        assert list(running_dir.rglob("em_uso.pdf"))
    finally:
        running.communicate("fim\n", timeout=60)
    assert not running_dir.exists()  # ela limpou o que era dela ao fechar


def test_old_folder_from_a_previous_version_is_removed_only_when_old(tmp_path: Path) -> None:
    """As pastas das versões antigas (uma por sessão, direto na raiz, sem
    trava) só saem depois de um bom tempo sem modificação."""
    root = tmp_path / ROOT_NAME
    recent = root / ("a" * 32)
    old = root / ("b" * 32)
    for folder in (recent, old):
        folder.mkdir(parents=True)
        (folder / "intermediario.pdf").write_bytes(b"x")
    _age(old, 3 * 24 * 3600)

    removed = TempManager(tmp_path).cleanup_orphans()

    assert removed == [old]
    assert recent.is_dir()


def test_cleanup_own_removes_everything_of_this_instance(tmp_path: Path) -> None:
    manager = TempManager(tmp_path)
    session = manager.session_dir(manager.new_session())
    (session / "intermediario.pdf").write_bytes(b"x")
    folder = manager.instance_dir

    manager.cleanup_own()

    assert not folder.exists()
    assert (tmp_path / ROOT_NAME).is_dir()  # a raiz, compartilhada, fica
