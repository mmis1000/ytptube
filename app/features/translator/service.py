from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.features.translator.constants import (
    DOWNLOAD_MODE_DOWNLOAD,
    SUBTITLE_MODE_NONE,
    SUBTITLE_MODE_TRANSLATE,
    normalize_download_mode,
    normalize_subtitle_mode,
    should_generate_subtitles,
)
from app.library.Events import Event, EventBus, Events
from app.library.Services import Services
from app.library.Singleton import Singleton

if TYPE_CHECKING:
    from aiohttp import web

    from app.library.config import Config
    from app.library.downloads import Download, DownloadQueue
    from app.library.ItemDTO import ItemDTO

LOG: logging.Logger = logging.getLogger("translator.service")

_SERVER_NOISE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{3}")
_PHASE_RE = re.compile(r"^\[(ASR|Translate|Subtitle)\s+(\d+)/(\d+)\]\s+(.+)$")


class TranslatorService(metaclass=Singleton):
    def __init__(self) -> None:
        self._jobs: dict[str, asyncio.Task] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._queue: DownloadQueue | None = None
        self._config: Config | None = None
        self._notify = EventBus.get_instance()

    @staticmethod
    def get_instance() -> TranslatorService:
        return TranslatorService()

    def attach(self, app: web.Application) -> None:
        from app.library.config import Config
        from app.library.downloads import DownloadQueue

        self._config = Config.get_instance()
        self._queue = DownloadQueue.get_instance()
        Services.get_instance().add("translator_service", self)
        app.on_shutdown.append(self.on_shutdown)

        async def handle_item_moved(event: Event, _) -> None:
            data = event.data if isinstance(event.data, dict) else {}
            if data.get("to") != "history":
                return

            item = data.get("item")
            if item is None or getattr(item, "status", None) != "finished":
                return

            extras = getattr(item, "extras", {}) or {}
            if not should_generate_subtitles(
                normalize_download_mode(extras.get("download_mode"), DOWNLOAD_MODE_DOWNLOAD),
                normalize_subtitle_mode(extras.get("subtitle_mode"), SUBTITLE_MODE_NONE),
            ):
                return

            await self.start_for_history_item(
                item.get_id(),
                source="auto",
                subtitle_mode=str(extras.get("subtitle_mode") or SUBTITLE_MODE_TRANSLATE),
            )

        self._notify.subscribe(Events.ITEM_MOVED, handle_item_moved, "TranslatorService.item_moved")

    async def on_shutdown(self, _: web.Application) -> None:
        for task in list(self._jobs.values()):
            task.cancel()
        for task in list(self._jobs.values()):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._jobs.clear()

    async def start_for_history_item(
        self,
        item_id: str,
        *,
        source: str = "api",
        force: bool = False,
        lang: str | None = None,
        mode: str | None = None,
        asr_mode: str | None = None,
        metadata_file: str | None = None,
        subtitle_mode: str | None = None,
    ) -> dict[str, Any]:
        queue = self._require_queue()
        config = self._require_config()
        if not item_id:
            message = "item_id is required"
            raise ValueError(message)

        item = await queue.done.get_by_id(item_id)
        if not item:
            raise KeyError(item_id)

        info = item.info
        media_file = info.get_file()
        requested_subtitle_mode = normalize_subtitle_mode(subtitle_mode, SUBTITLE_MODE_TRANSLATE)
        if requested_subtitle_mode == SUBTITLE_MODE_NONE:
            message = "subtitle_mode must not be none when requesting subtitle generation."
            raise ValueError(message)
        if not media_file or not media_file.exists():
            message = "item has no downloaded file."
            raise ValueError(message)

        if item_id in self._jobs and not self._jobs[item_id].done():
            return {
                "status": "already_running",
                "item_id": item_id,
                "message": f"Subtitle generation already running for {info.title}.",
            }

        if not force and self._has_existing_sidecars(media_file, requested_subtitle_mode):
            await self._mark_completed(info, media_file, message="Subtitle sidecars already exist.")
            return {
                "status": "already_generated",
                "item_id": item_id,
                "message": "Subtitle sidecars already exist.",
            }

        workspace_output = self._workspace_for_item(item_id) / "output"
        if not force and self._has_output_sidecars(workspace_output, media_file.stem, requested_subtitle_mode):
            copied = await self._copy_sidecars(media_file, workspace_output)
            await self._mark_completed(
                info,
                media_file,
                output_dir=workspace_output,
                message="Recovered subtitle sidecars from previous workspace.",
            )
            return {
                "status": "recovered_from_workspace",
                "item_id": item_id,
                "message": "Recovered subtitle sidecars from previous workspace.",
                "files": copied,
            }

        payload = {
            "source": source,
            "force": force,
            "lang": str(lang or config.translator_locale),
            "mode": str(mode or config.translator_mode),
            "asr_mode": str(asr_mode or config.translator_asr_mode),
            "metadata_file": metadata_file,
            "subtitle_mode": requested_subtitle_mode,
        }

        task = asyncio.create_task(self._run_job(item_id=item_id, payload=payload), name=f"subtitle-job-{item_id}")
        self._jobs[item_id] = task
        return {
            "status": "accepted",
            "item_id": item_id,
            "message": f"Subtitle generation queued for {info.title}.",
            "payload": payload,
        }

    async def _run_job(self, item_id: str, payload: dict[str, Any]) -> None:
        queue = self._require_queue()
        try:
            item = await queue.done.get_by_id(item_id)
            if not item:
                self._raise_missing_item(item_id)

            info = item.info
            media_file = info.get_file()
            if not media_file or not media_file.exists():
                self._raise_missing_media_file()

            workspace = self._workspace_for_item(item_id)
            input_dir, output_dir, metadata_path = await self._prepare_workspace(info, media_file, workspace, payload)
            cmd = self._build_command(input_dir=input_dir, output_dir=output_dir, payload=payload, metadata_path=metadata_path)

            await self._update_item(
                item,
                state="queued",
                message="Subtitle generation queued.",
                workspace=workspace,
                command=cmd,
                payload=payload,
                output_dir=output_dir,
            )

            async with self._lock:
                await self._update_item(
                    item,
                    state="running",
                    message="Subtitle generation started.",
                    workspace=workspace,
                    command=cmd,
                    payload=payload,
                    output_dir=output_dir,
                )
                await self._spawn_and_monitor(item, workspace, cmd)
                await self._copy_sidecars(media_file, output_dir)
                await self._mark_completed(item.info, media_file, output_dir=output_dir, message="Subtitle generation completed.")
        except asyncio.CancelledError:
            await self._safe_fail(item_id, "Subtitle generation cancelled.")
            raise
        except Exception as exc:
            LOG.exception("Subtitle generation failed for %s", item_id)
            await self._safe_fail(item_id, str(exc))
        finally:
            self._jobs.pop(item_id, None)

    async def _spawn_and_monitor(self, item: Download, workspace: Path, cmd: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(Path(self._require_config().translator_project_path)),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        log_path = workspace / "translator.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        recent_lines: deque[str] = deque(maxlen=20)

        async def consume(stream: asyncio.StreamReader | None, label: str) -> None:
            if stream is None:
                return
            with log_path.open("a", encoding="utf-8") as handle:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="ignore").rstrip()
                    tagged = f"[{label}] {text}"
                    handle.write(f"{tagged}\n")
                    handle.flush()
                    recent_lines.append(tagged)
                    if self._is_interesting_line(text):
                        await self._apply_progress_line(item, text, log_path)

        await asyncio.gather(consume(process.stdout, "stdout"), consume(process.stderr, "stderr"))
        code = await process.wait()
        if code != 0:
            raise RuntimeError(self._format_translator_failure(code=code, log_path=log_path, recent_lines=recent_lines))

    def _format_translator_failure(self, *, code: int, log_path: Path, recent_lines: deque[str]) -> str:
        message = f"translator exited with code {code}; log: {log_path}"
        if recent_lines:
            return f"{message}; last output:\n" + "\n".join(recent_lines)
        return message

    async def _prepare_workspace(
        self,
        info: ItemDTO,
        media_file: Path,
        workspace: Path,
        payload: dict[str, Any],
    ) -> tuple[Path, Path, Path]:
        input_dir = workspace / "input"
        output_dir = workspace / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        link_path = input_dir / media_file.name
        if link_path.exists() or link_path.is_symlink():
            link_path.unlink()

        try:
            os.link(media_file, link_path)
        except OSError:
            shutil.copy2(media_file, link_path)

        metadata_override = payload.get("metadata_file")
        if metadata_override:
            return input_dir, output_dir, Path(str(metadata_override))

        metadata_path = workspace / "metadata.json"
        metadata: dict[str, Any] = {
            "title": info.title,
            "summary": info.description or info.extras.get("description") or "",
            "glossary": {
                "cvs": [],
                "characters": [],
                "terms": [],
            },
            "track_list": [
                {
                    "filename": media_file.name,
                    "title": info.title,
                }
            ],
        }

        uploader = info.extras.get("uploader") or info.extras.get("channel")
        if uploader:
            metadata["glossary"]["cvs"].append({"ja": str(uploader), "zh": str(uploader)})

        metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        return input_dir, output_dir, metadata_path

    def _build_command(
        self,
        *,
        input_dir: Path,
        output_dir: Path,
        payload: dict[str, Any],
        metadata_path: Path,
    ) -> list[str]:
        config = self._require_config()
        project_path = Path(config.translator_project_path)
        if not project_path.exists():
            message = f"translator project path does not exist: {project_path}"
            raise ValueError(message)
        dist_cli = project_path / "dist" / "cli.js"
        if dist_cli.exists():
            cmd = [
                config.translator_node_exe,
                str(dist_cli),
            ]
        else:
            cmd = [
                config.translator_npm_exe,
                "run",
                "start",
                "--",
            ]

        cmd.extend(
            [
                "--input",
                str(input_dir),
                "--output",
                str(output_dir),
                "--metadata",
                str(metadata_path),
                "--lang",
                str(payload.get("lang") or config.translator_locale),
                "--mode",
                str(payload.get("mode") or config.translator_mode),
                "--asr",
                str(payload.get("asr_mode") or config.translator_asr_mode),
                "--subtitle-mode",
                str(payload.get("subtitle_mode") or SUBTITLE_MODE_TRANSLATE),
            ]
        )

        subtitle_mode = str(payload.get("subtitle_mode") or SUBTITLE_MODE_TRANSLATE)
        if subtitle_mode != "transcribe" and config.translator_server_url:
            cmd.extend(["--server-url", config.translator_server_url])
        elif subtitle_mode != "transcribe" and config.translator_hf_repo:
            cmd.extend(["--hf-repo", config.translator_hf_repo])
            if config.translator_hf_file:
                cmd.extend(["--hf-file", config.translator_hf_file])
        elif subtitle_mode != "transcribe" and config.translator_model_path:
            cmd.extend(["--model", config.translator_model_path])
        elif subtitle_mode != "transcribe":
            message = (
                "translator model/server is not configured. Set YTP_TRANSLATOR_SERVER_URL "
                "or YTP_TRANSLATOR_MODEL_PATH."
            )
            raise ValueError(message)

        if subtitle_mode != "transcribe" and not config.translator_server_url:
            cmd.extend(
                [
                    "--llama-server",
                    config.translator_llama_server_exe,
                    "--port",
                    str(config.translator_port),
                    "--gpu-layers",
                    str(config.translator_gpu_layers),
                    "--ctx-size",
                    str(config.translator_ctx_size),
                    "--parallel",
                    str(config.translator_parallel),
                ]
            )
            if config.translator_mtp:
                cmd.append("--mtp")
                cmd.extend(["--spec-draft-n-max", str(config.translator_spec_draft_n_max)])

        if (payload.get("asr_mode") or config.translator_asr_mode) == "python":
            if config.translator_python_exe:
                cmd.extend(["--python-exe", config.translator_python_exe])
            if config.translator_asr_script:
                cmd.extend(["--asr-script", config.translator_asr_script])
        if config.translator_uv_exe:
            cmd.extend(["--uv-exe", config.translator_uv_exe])
        return cmd

    async def _apply_progress_line(self, item: Download, line: str, log_path: Path) -> None:
        update: dict[str, Any] = {
            "last_line": line,
            "log_file": str(log_path),
        }
        if match := _PHASE_RE.match(line):
            phase_name, current, total, track = match.groups()
            update["phase"] = phase_name.lower()
            update["progress"] = {
                "current": int(current),
                "total": int(total),
                "track": track,
            }
        elif line.startswith("[Metadata]"):
            update["phase"] = "metadata"
        elif line.startswith("[TranslateServer]"):
            update["phase"] = "server"
        elif line.startswith("=== Complete ==="):
            update["phase"] = "complete"
        elif line.startswith("Found "):
            update["phase"] = "discover"

        await self._update_item(item, state="running", message=line, progress_update=update)

    async def _copy_sidecars(self, media_file: Path, output_dir: Path) -> list[str]:
        stem = media_file.stem
        copied: list[str] = []
        suffixes = [
            ".lrc",
            ".vtt",
            ".translation.json",
            ".transcription.json",
            ".windows.json",
            ".surgical.json",
        ]
        for suffix in suffixes:
            source = output_dir / f"{stem}{suffix}"
            if not source.exists():
                continue
            dest = media_file.with_name(f"{media_file.stem}{suffix}")
            shutil.copy2(source, dest)
            copied.append(dest.name)

        metadata = output_dir / "metadata.json"
        if metadata.exists():
            dest = media_file.with_name(f"{media_file.stem}.metadata.json")
            shutil.copy2(metadata, dest)
            copied.append(dest.name)
        return copied

    async def _mark_completed(
        self,
        info: ItemDTO,
        media_file: Path,
        *,
        output_dir: Path | None = None,
        message: str,
    ) -> None:
        queue = self._require_queue()
        item = await queue.done.get_by_id(info.get_id())
        if not item:
            return

        subtitle_files = sorted(
            path.name
            for path in media_file.parent.glob(f"{media_file.stem}.*")
            if path.suffix in {".lrc", ".vtt"}
            or path.name.endswith(
                (
                    ".translation.json",
                    ".transcription.json",
                    ".windows.json",
                    ".surgical.json",
                    ".metadata.json",
                )
            )
        )
        try:
            item.info.sidecar = item.info.get_file_sidecar()
        except Exception:
            item.info.sidecar = {}
        await self._update_item(
            item,
            state="finished",
            message=message,
            progress_update={
                "phase": "complete",
                "completed_at": datetime.now(tz=UTC).isoformat(),
                "output_dir": str(output_dir) if output_dir else None,
                "subtitle_files": subtitle_files,
            },
        )

    async def _safe_fail(self, item_id: str, message: str) -> None:
        queue = self._require_queue()
        item = await queue.done.get_by_id(item_id)
        if not item:
            return
        await self._update_item(item, state="error", message=message)

    async def _update_item(
        self,
        item: Download,
        *,
        state: str,
        message: str,
        workspace: Path | None = None,
        command: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        output_dir: Path | None = None,
        progress_update: dict[str, Any] | None = None,
    ) -> None:
        queue = self._require_queue()
        progress = dict(item.info.extras.get("subtitle_generation") or {})
        progress.setdefault("requested_at", datetime.now(tz=UTC).isoformat())
        progress.update(
            {
                "state": state,
                "message": message,
                "updated_at": datetime.now(tz=UTC).isoformat(),
            }
        )
        if workspace is not None:
            progress["workspace"] = str(workspace)
        if output_dir is not None:
            progress["output_dir"] = str(output_dir)
        if command is not None:
            progress["command"] = command
        if payload is not None:
            progress["payload"] = payload
        if progress_update:
            progress.update({k: v for k, v in progress_update.items() if v is not None})

        item.info.extras["subtitle_generation"] = progress
        item.info.msg = message
        await queue.done.put(item, no_notify=True)
        self._notify.emit(Events.ITEM_UPDATED, data=item.info)

    @staticmethod
    def _raise_missing_item(item_id: str) -> None:
        raise KeyError(item_id)

    @staticmethod
    def _raise_missing_media_file() -> None:
        message = "item has no downloaded file."
        raise ValueError(message)

    def _workspace_for_item(self, item_id: str) -> Path:
        return Path(self._require_config().translator_workspace) / item_id

    def _required_sidecar_suffixes(self, subtitle_mode: str) -> tuple[str, ...]:
        normalized_mode = normalize_subtitle_mode(subtitle_mode, SUBTITLE_MODE_TRANSLATE)
        if normalized_mode == "transcribe":
            return (".lrc", ".vtt", ".transcription.json")
        return (".lrc", ".vtt", ".translation.json", ".windows.json")

    def _has_existing_sidecars(self, media_file: Path, subtitle_mode: str) -> bool:
        return all(
            (media_file.with_name(f"{media_file.stem}{suffix}")).exists()
            for suffix in self._required_sidecar_suffixes(subtitle_mode)
        )

    def _has_output_sidecars(self, output_dir: Path, stem: str, subtitle_mode: str) -> bool:
        return all((output_dir / f"{stem}{suffix}").exists() for suffix in self._required_sidecar_suffixes(subtitle_mode))

    def _is_interesting_line(self, line: str) -> bool:
        if not line or _SERVER_NOISE_RE.match(line):
            return False
        prefixes = (
            "=== asmr-translator ===",
            "[Metadata]",
            "[ASR ",
            "[Translate ",
            "[Subtitle ",
            "[TranslateServer]",
            "Found ",
            "Done:",
            "Skipped",
            "=== Complete ===",
            "Processed:",
            "Output:",
            "Fatal error:",
            "ERROR:",
        )
        return line.startswith(prefixes) or " clean segments " in line

    def _require_queue(self) -> DownloadQueue:
        if self._queue is None:
            message = "translator queue is not initialized"
            raise RuntimeError(message)
        return self._queue

    def _require_config(self) -> Config:
        if self._config is None:
            message = "translator config is not initialized"
            raise RuntimeError(message)
        return self._config
