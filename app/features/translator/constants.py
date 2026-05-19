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
