from pathlib import Path

from app.features.translator.service import TranslatorService


def test_translate_recovery_requires_translation_outputs(tmp_path: Path) -> None:
    service = TranslatorService.get_instance()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    (output_dir / "sample.lrc").write_text("")
    (output_dir / "sample.vtt").write_text("")
    (output_dir / "sample.transcription.json").write_text("{}")

    assert service._has_output_sidecars(output_dir, "sample", "translate") is False

    (output_dir / "sample.translation.json").write_text("{}")
    (output_dir / "sample.windows.json").write_text("[]")

    assert service._has_output_sidecars(output_dir, "sample", "translate") is True


def test_transcribe_recovery_does_not_require_translation_outputs(tmp_path: Path) -> None:
    service = TranslatorService.get_instance()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    (output_dir / "sample.lrc").write_text("")
    (output_dir / "sample.vtt").write_text("")
    (output_dir / "sample.transcription.json").write_text("{}")

    assert service._has_output_sidecars(output_dir, "sample", "transcribe") is True


def test_existing_translate_sidecars_require_translation_files(tmp_path: Path) -> None:
    service = TranslatorService.get_instance()
    media_file = tmp_path / "sample.opus"
    media_file.write_text("audio")

    (tmp_path / "sample.lrc").write_text("")
    (tmp_path / "sample.vtt").write_text("")
    (tmp_path / "sample.transcription.json").write_text("{}")

    assert service._has_existing_sidecars(media_file, "translate") is False

    (tmp_path / "sample.translation.json").write_text("{}")
    (tmp_path / "sample.windows.json").write_text("[]")

    assert service._has_existing_sidecars(media_file, "translate") is True
