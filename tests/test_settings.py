"""
Testes das configurações (`app/config/settings.py`).

O que está sendo protegido: um `settings.json` estragado — cortado no meio,
editado à mão com valores errados, de uma versão futura com campos novos —
nunca impede o aplicativo de abrir nem apaga o que estava certo; e salvar
nunca deixa o arquivo pela metade.

Todos os testes usam um arquivo na pasta temporária do teste, nunca as
configurações de quem usa a máquina.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from app.config import settings as settings_module
from app.config.settings import (
    DATA_DIR_ENV,
    Settings,
    SettingsManager,
    get_app_data_dir,
    get_documents_dir,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _folder(tmp_path: Path, name: str = "Saida") -> str:
    return str(tmp_path / name)


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    manager = SettingsManager(tmp_path / "settings.json")

    assert manager.settings == Settings()


def test_truncated_json_gives_defaults_without_crashing(tmp_path: Path) -> None:
    path = _write(tmp_path / "settings.json", '{"theme": "dark", "max_concurrent_ta')

    manager = SettingsManager(path)

    assert manager.settings == Settings()
    # O arquivo estragado não é apagado nem regravado só por ter sido lido.
    assert path.read_text(encoding="utf-8") == '{"theme": "dark", "max_concurrent_ta'


def test_json_that_is_not_an_object_gives_defaults(tmp_path: Path) -> None:
    for content in ("[1, 2, 3]", '"texto"', "null", "42"):
        manager = SettingsManager(_write(tmp_path / "settings.json", content))
        assert manager.settings == Settings()


def test_binary_garbage_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xff\xfe\x00\x81 lixo")

    assert SettingsManager(path).settings == Settings()


def test_wrong_types_fall_back_field_by_field(tmp_path: Path) -> None:
    data = {
        "output_folder": 123,
        "open_folder_after_finish": "talvez",
        "show_mascot_messages": [],
        "animations_enabled": None,
        "ask_before_overwrite": {"a": 1},
        "max_concurrent_tasks": "muitos",
        "theme": 7,
        "ffmpeg_path": False,
    }

    settings = Settings.from_dict(data)

    assert settings == Settings()


def test_booleans_are_normalized(tmp_path: Path) -> None:
    settings = Settings.from_dict(
        {
            "open_folder_after_finish": "false",
            "show_mascot_messages": 0,
            "animations_enabled": "Sim",
            "ask_before_overwrite": 1,
        }
    )

    assert settings.open_folder_after_finish is False
    assert settings.show_mascot_messages is False
    assert settings.animations_enabled is True
    assert settings.ask_before_overwrite is True


@pytest.mark.parametrize("theme", ["roxo", "", "sistema", None])
def test_invalid_theme_falls_back_to_system(theme) -> None:
    assert Settings.from_dict({"theme": theme}).theme == "system"


def test_theme_is_normalized() -> None:
    assert Settings.from_dict({"theme": " DARK "}).theme == "dark"


@pytest.mark.parametrize("value", [0, 9, -1, 100, True, 2.5, "0"])
def test_concurrency_out_of_range_falls_back(value) -> None:
    assert Settings.from_dict({"max_concurrent_tasks": value}).max_concurrent_tasks == 2


@pytest.mark.parametrize("value, expected", [(1, 1), (8, 8), (4.0, 4), ("3", 3)])
def test_concurrency_in_range_is_kept(value, expected: int) -> None:
    assert Settings.from_dict({"max_concurrent_tasks": value}).max_concurrent_tasks == expected


@pytest.mark.parametrize("folder", ["", "   ", "pasta/relativa", "C:\x00ruim"])
def test_invalid_output_folder_falls_back(folder: str) -> None:
    assert Settings.from_dict({"output_folder": folder}).output_folder == Settings().output_folder


def test_unknown_fields_are_ignored(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "settings.json",
        json.dumps({"theme": "light", "campo_de_uma_versao_futura": True, "outro": [1]}),
    )

    settings = SettingsManager(path).settings

    assert settings.theme == "light"
    assert not hasattr(settings, "campo_de_uma_versao_futura")


def test_partially_valid_configuration_keeps_the_valid_fields(tmp_path: Path) -> None:
    """Um campo estragado não pode levar os outros junto."""
    folder = _folder(tmp_path, "Meus Convertidos")
    path = _write(
        tmp_path / "settings.json",
        json.dumps(
            {
                "output_folder": folder,
                "theme": "roxo",
                "max_concurrent_tasks": 50,
                "animations_enabled": False,
                "ask_before_overwrite": "nao",
            }
        ),
    )

    settings = SettingsManager(path).settings

    assert settings.output_folder == folder
    assert settings.animations_enabled is False
    assert settings.ask_before_overwrite is False
    assert settings.theme == "system"
    assert settings.max_concurrent_tasks == 2


def test_update_validates_before_saving(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)

    manager.update(theme="dark", max_concurrent_tasks=99, output_folder="")

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["theme"] == "dark"
    assert saved["max_concurrent_tasks"] == 2
    assert saved["output_folder"] == Settings().output_folder


def test_save_round_trips_unicode_paths(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    folder = _folder(tmp_path, "Conversões de Março")
    SettingsManager(path).update(output_folder=folder)

    assert SettingsManager(path).settings.output_folder == folder


def test_a_crash_while_saving_keeps_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gravação cai no meio (o disco enche, o programa é derrubado): o
    arquivo anterior continua inteiro e nenhum temporário fica para trás."""
    path = tmp_path / "settings.json"
    manager = SettingsManager(path)
    manager.update(theme="dark", max_concurrent_tasks=4)
    previous = path.read_text(encoding="utf-8")

    def broken_dump(obj, handle, **_options):
        handle.write('{"theme": "li')
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(settings_module.json, "dump", broken_dump)
    with pytest.raises(OSError):
        manager.update(theme="light")

    assert path.read_text(encoding="utf-8") == previous
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]
    assert SettingsManager(path).settings.theme == "dark"


def test_saving_replaces_the_file_in_one_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O arquivo definitivo só é tocado por `os.replace`, depois de o
    temporário estar completo."""
    path = tmp_path / "settings.json"
    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(source, destination):
        assert json.loads(Path(source).read_text(encoding="utf-8"))["theme"] == "light"
        replaced.append((Path(source).name, Path(destination).name))
        real_replace(source, destination)

    monkeypatch.setattr(settings_module.os, "replace", spy)
    SettingsManager(path).update(theme="light")

    assert len(replaced) == 1
    assert replaced[0][1] == "settings.json"
    assert replaced[0][0] != "settings.json"


def test_data_dir_can_be_redirected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "dados isolados"))

    assert get_app_data_dir() == tmp_path / "dados isolados"
    assert (tmp_path / "dados isolados").is_dir()


@pytest.mark.windows
@pytest.mark.skipif(sys.platform != "win32", reason="pastas conhecidas são do Windows")
def test_documents_folder_comes_from_windows() -> None:
    """A pasta Documentos é perguntada ao Windows, e não montada à mão: ela
    pode ter sido movida ou estar dentro do OneDrive."""
    documents = get_documents_dir()

    assert documents.is_absolute()
    assert documents.is_dir()
    assert settings_module._windows_documents_dir() == documents


def test_default_output_folder_is_inside_documents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings_module, "_windows_documents_dir", lambda: tmp_path / "OneDrive" / "Documentos")

    assert settings_module.get_default_output_dir() == (
        tmp_path / "OneDrive" / "Documentos" / "FileMorph" / "Convertidos"
    )
