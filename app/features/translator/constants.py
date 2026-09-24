from __future__ import annotations

DOWNLOAD_MODE_DOWNLOAD: str = "download"
DOWNLOAD_MODE_SUBTITLE: str = "download+subtitle"
VALID_DOWNLOAD_MODES: tuple[str, ...] = (
    DOWNLOAD_MODE_DOWNLOAD,
    DOWNLOAD_MODE_SUBTITLE,
)

SUBTITLE_MODE_NONE: str = "none"
SUBTITLE_MODE_TRANSCRIBE: str = "transcribe"
SUBTITLE_MODE_TRANSLATE: str = "translate"
VALID_SUBTITLE_MODES: tuple[str, ...] = (
    SUBTITLE_MODE_NONE,
    SUBTITLE_MODE_TRANSCRIBE,
    SUBTITLE_MODE_TRANSLATE,
)

DEFAULT_TRANSLATOR_HF_REPOS: dict[tuple[str, str], str] = {
    ("zh-tw", "echo"): "mmis1000/asmr-qwen3.5-9b-zh-tw-echo-gguf-v0.2:Q8_0",
    ("zh-tw", "base"): "mmis1000/asmr-qwen3.5-9b-zh-tw-gguf-v0.2:Q8_0",
    ("zh-cn", "echo"): "mmis1000/asmr-qwen3.5-9b-zh-cn-echo-gguf-v0.2:Q8_0",
    ("zh-cn", "base"): "mmis1000/asmr-qwen3.5-9b-zh-cn-gguf-v0.2:Q8_0",
}


def default_translator_hf_repo(locale: object, mode: object) -> str:
    key = (str(locale).strip().lower(), str(mode).strip().lower())
    try:
        return DEFAULT_TRANSLATOR_HF_REPOS[key]
    except KeyError as exc:
        msg = f"No default translator model for locale={key[0]!r}, mode={key[1]!r}"
        raise ValueError(msg) from exc


def normalize_download_mode(value: object, default: str = DOWNLOAD_MODE_DOWNLOAD) -> str:
    if value is None:
        return default

    normalized = str(value).strip().lower()
    if normalized not in VALID_DOWNLOAD_MODES:
        msg = f"download_mode must be one of: {', '.join(VALID_DOWNLOAD_MODES)}"
        raise ValueError(msg)
    return normalized


def normalize_subtitle_mode(value: object, default: str = SUBTITLE_MODE_NONE) -> str:
    if value is None:
        return default

    normalized = str(value).strip().lower()
    if normalized not in VALID_SUBTITLE_MODES:
        msg = f"subtitle_mode must be one of: {', '.join(VALID_SUBTITLE_MODES)}"
        raise ValueError(msg)
    return normalized


def should_generate_subtitles(download_mode: str, subtitle_mode: str) -> bool:
    return download_mode == DOWNLOAD_MODE_SUBTITLE and subtitle_mode != SUBTITLE_MODE_NONE
