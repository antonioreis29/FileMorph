"""
Testes da animação do mascote da Fase 8 (item 34 do briefing).

Animação é difícil de testar porque o resultado é visual — mas a parte
que decide *como* o mascote se move é função pura (`pose_for`), e é ela
que estes testes verificam: sem abrir janela, sem temporizador e sem
depender do relógio. O que sobra para o olho é o desenho em si.

O que estes testes protegem, em uma frase: o mascote não pode
deformar-se além do que o widget reserva de espaço (senão a figura
aparece cortada), não pode mudar de volume (senão parece redimensionada
em vez de elástica), e toda reação tem que terminar voltando ao repouso.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="o módulo do mascote vive na camada de UI")

from app.ui.mascot import (  # noqa: E402
    NEUTRAL_POSE,
    MascotState,
    Pose,
    duration_of,
    pose_for,
)

# Estados contínuos (respiram para sempre) e reações (têm fim).
CONTINUOUS = (MascotState.IDLE, MascotState.READY, MascotState.WORKING)
REACTIONS = (MascotState.HAPPY, MascotState.SAD, MascotState.CANCELLED)

# A folga que o widget reserva acima da figura (`_HEADROOM` em
# app/ui/mascot.py), em fração da altura dela. O desenho é ancorado na
# base, então esticar e pular consomem essa mesma folga — juntos.
HEADROOM = 0.40

# A folga lateral (`_SIDEROOM`), em fração da largura. O deslocamento é
# medido em altura, e a figura do projeto é mais larga que alta, então
# comparar com a fração de largura é o limite conservador.
SIDEROOM = 0.20


def _area(pose: Pose) -> float:
    return pose.scale_x * pose.scale_y


def test_every_state_has_a_pose() -> None:
    """`pose_for` tem que ser total: um estado sem pose viraria exceção
    dentro do `paintEvent`, que é o pior lugar possível para uma."""
    for state in MascotState:
        assert isinstance(pose_for(state, 0.0), Pose)


def test_continuous_states_never_end_and_reactions_always_do() -> None:
    for state in CONTINUOUS:
        assert duration_of(state) is None
    for state in REACTIONS:
        duration = duration_of(state)
        assert duration is not None and duration > 0


def test_squash_preserves_volume() -> None:
    """Esmagar tem que alargar na mesma proporção.

    Sem isso a figura parece aumentar e diminuir de tamanho, e não se
    deformar — é a diferença entre massinha e um zoom.
    """
    for state in MascotState:
        for step in range(60):
            pose = pose_for(state, step / 20)
            assert _area(pose) == pytest.approx(1.0, abs=0.01)


def test_animation_stays_inside_the_space_the_widget_reserves() -> None:
    """O que esticar para cima e o que subir do chão saem da mesma folga.

    Se a soma passar do que o widget reserva, a figura é desenhada fora
    dele e aparece cortada — o tipo de defeito que só aparece no
    instante mais alto de um pulo, difícil de notar olhando.
    """
    for state in MascotState:
        for step in range(200):
            pose = pose_for(state, step / 40)
            # O mascote nunca afunda abaixo da linha em que se apoia.
            assert pose.offset_y <= 0.0
            acima = max(0.0, pose.scale_y - 1.0) + (-pose.offset_y)
            assert acima <= HEADROOM
            assert abs(pose.offset_x) <= SIDEROOM
            # Nada de figura sumindo ou dobrando de tamanho.
            assert 0.7 < pose.scale_x < 1.3
            assert 0.7 < pose.scale_y < 1.3


def test_breathing_returns_to_where_it_started() -> None:
    """A respiração é um ciclo: se não fechasse, haveria um salto visível
    a cada volta."""
    for state, period in ((MascotState.IDLE, 3.0), (MascotState.READY, 1.8)):
        assert pose_for(state, 0.0).scale_y == pytest.approx(
            pose_for(state, period).scale_y, abs=1e-6
        )


def test_working_is_more_agitated_than_idle() -> None:
    """O estado tem que ser legível sem ler o texto: quem olha de longe
    precisa ver que o aplicativo está trabalhando."""
    idle = max(abs(1 - pose_for(MascotState.IDLE, t / 40).scale_y) for t in range(200))
    working = max(
        abs(1 - pose_for(MascotState.WORKING, t / 40).scale_y) for t in range(200)
    )
    assert working > idle


def test_only_working_sways_sideways() -> None:
    """O balanço lateral é o que distingue "trabalhando" de "respirando
    rápido" — os outros estados contínuos ficam no lugar."""
    sway = max(abs(pose_for(MascotState.WORKING, t / 40).offset_x) for t in range(200))
    assert sway > 0
    for state in (MascotState.IDLE, MascotState.READY):
        assert all(pose_for(state, t / 40).offset_x == 0 for t in range(200))


def test_celebration_leaves_the_ground_and_comes_back_smaller() -> None:
    """Pulos que diminuem: o segundo é mais baixo que o primeiro, e no
    fim o mascote está parado no chão."""
    duration = duration_of(MascotState.HAPPY)
    alturas = [-pose_for(MascotState.HAPPY, duration * i / 100).offset_y for i in range(100)]
    primeiro = max(alturas[:50])
    segundo = max(alturas[50:])
    assert primeiro > segundo > 0


def test_every_reaction_ends_in_the_resting_pose() -> None:
    """Ao terminar, a reação tem que entregar o mascote em repouso.

    O widget troca de estado quando o tempo acaba; se a última pose não
    fosse a neutra, essa troca apareceria como um pulo da figura.
    """
    for state in REACTIONS:
        final = pose_for(state, duration_of(state))
        assert final == NEUTRAL_POSE


def test_pose_is_defined_outside_the_expected_range() -> None:
    """Tempo negativo ou muito além do fim não pode explodir.

    O relógio do widget é somado quadro a quadro, e um quadro perdido
    (janela minimizada, máquina travada) pode passar do fim antes de a
    troca de estado acontecer.
    """
    for state in MascotState:
        assert pose_for(state, -5.0) == pose_for(state, 0.0)
        assert isinstance(pose_for(state, 10_000.0), Pose)
