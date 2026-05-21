import asyncio
from collections import deque
from pathlib import Path
from types import SimpleNamespace

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


def test_format_translator_failure_includes_log_path_and_recent_lines(tmp_path: Path) -> None:
    service = TranslatorService.get_instance()
    log_path = tmp_path / "translator.log"

    message = service._format_translator_failure(
        code=1,
        log_path=log_path,
        recent_lines=deque(["[stderr] boom", "[stdout] detail"], maxlen=20),
    )

    assert "translator exited with code 1" in message
    assert str(log_path) in message
    assert "[stderr] boom" in message
    assert "[stdout] detail" in message


def test_format_translator_failure_without_recent_lines_still_points_to_log(tmp_path: Path) -> None:
    service = TranslatorService.get_instance()
    log_path = tmp_path / "translator.log"

    message = service._format_translator_failure(
        code=1,
        log_path=log_path,
        recent_lines=deque([], maxlen=20),
    )

    assert message == f"translator exited with code 1; log: {log_path}"


async def _collect_stream_records(chunks: list[bytes]) -> list[str]:
    service = TranslatorService.get_instance()
    reader = asyncio.StreamReader()
    for chunk in chunks:
        reader.feed_data(chunk)
    reader.feed_eof()
    return [text async for text in service._iter_stream_records(reader)]


def test_iter_stream_records_handles_carriage_returns_and_long_chunks() -> None:
    records = asyncio.run(
        _collect_stream_records(
            [
                b"progress 1/3\rprogress 2/3\r",
                b"progress 3/3\nfinal line without newline",
            ]
        )
    )

    assert records == ["progress 1/3", "progress 2/3", "progress 3/3", "final line without newline"]


def test_iter_stream_records_reassembles_split_lines() -> None:
    records = asyncio.run(_collect_stream_records([b"hello", b" world\nnext", b" line\rthird"]))

    assert records == ["hello world", "next line", "third"]


def test_build_command_prefers_built_dist_cli_when_available(tmp_path: Path) -> None:
    service = TranslatorService.get_instance()
    project_path = tmp_path / "translator-project"
    dist_dir = project_path / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "cli.js").write_text("console.log('stub')", encoding="utf-8")
    previous_config = service._config
    service._config = SimpleNamespace(
        translator_project_path=str(project_path),
        translator_npm_exe="npm",
        translator_node_exe="node-custom",
        translator_locale="zh-tw",
        translator_mode="echo",
        translator_asr_mode="python",
        translator_server_url="",
        translator_hf_repo="mmis1000/example-repo",
        translator_hf_file="example-q8_0.gguf",
        translator_model_path="",
        translator_llama_server_exe="/opt/llama.cpp/llama-server",
        translator_port=8181,
        translator_gpu_layers="all",
        translator_ctx_size=8192,
        translator_parallel=1,
        translator_mtp=False,
        translator_spec_draft_n_max=2,
        translator_python_exe="/app/translator/asr/.venv/bin/python",
        translator_asr_script="",
        translator_uv_exe="/usr/local/bin/uv",
    )
    try:
        cmd = service._build_command(
            input_dir=tmp_path / "input",
            output_dir=tmp_path / "output",
            payload={},
            metadata_path=tmp_path / "metadata.json",
        )
    finally:
        service._config = previous_config

    assert cmd[:2] == ["node-custom", str(dist_dir / "cli.js")]
    assert "--hf-file" in cmd
    assert cmd[cmd.index("--hf-file") + 1] == "example-q8_0.gguf"


def test_build_command_falls_back_to_npm_start_without_built_dist(tmp_path: Path) -> None:
    service = TranslatorService.get_instance()
    project_path = tmp_path / "translator-project"
    project_path.mkdir()
    previous_config = service._config
    service._config = SimpleNamespace(
        translator_project_path=str(project_path),
        translator_npm_exe="npm-custom",
        translator_node_exe="node-custom",
        translator_locale="zh-tw",
        translator_mode="echo",
        translator_asr_mode="python",
        translator_server_url="",
        translator_hf_repo="mmis1000/example-repo",
        translator_hf_file="example-q8_0.gguf",
        translator_model_path="",
        translator_llama_server_exe="/opt/llama.cpp/llama-server",
        translator_port=8181,
        translator_gpu_layers="all",
        translator_ctx_size=8192,
        translator_parallel=1,
        translator_mtp=False,
        translator_spec_draft_n_max=2,
        translator_python_exe="/app/translator/asr/.venv/bin/python",
        translator_asr_script="",
        translator_uv_exe="/usr/local/bin/uv",
    )
    try:
        cmd = service._build_command(
            input_dir=tmp_path / "input",
            output_dir=tmp_path / "output",
            payload={},
            metadata_path=tmp_path / "metadata.json",
        )
    finally:
        service._config = previous_config

    assert cmd[:4] == ["npm-custom", "run", "start", "--"]
    assert "--hf-file" in cmd
    assert cmd[cmd.index("--hf-file") + 1] == "example-q8_0.gguf"
