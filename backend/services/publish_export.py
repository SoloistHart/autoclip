"""
发布导出：按需把一条切片渲成可直接上传的成片。

默认流水线仍出 16:9 stream-copy 素材；用户点「发布导出」才重编码。
一个 ffmpeg 调用：帧精确裁切 + 画幅预设 + 烧字幕 + 标题卡。
方案见 docs/QUALITY_AND_PUBLISH_PLAN.md 线 2。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from backend.pipeline.quality import to_seconds, load_srt_chunks
from backend.services.shorts_subtitles import build_ass, build_caption_pages, build_word_caption_pages, slice_srt
from backend.utils.ffmpeg_utils import get_ffmpeg_path, get_ffprobe_path

logger = logging.getLogger(__name__)

PRESETS: Dict[str, Dict[str, Any]] = {
    "douyin": {"label": "抖音 9:16", "w": 1080, "h": 1920, "layout": "blur", "max_sec": None},
    "xiaohongshu": {"label": "小红书 9:16", "w": 1080, "h": 1920, "layout": "blur", "max_sec": None},
    "shorts": {"label": "YouTube Shorts", "w": 1080, "h": 1920, "layout": "smart", "max_sec": None},
    "tiktok": {"label": "TikTok", "w": 1080, "h": 1920, "layout": "smart", "max_sec": None},
    "bilibili": {"label": "B 站横屏", "w": 1920, "h": 1080, "layout": "fit", "max_sec": None},
    "original": {"label": "原画重编码", "w": None, "h": None, "layout": "none", "max_sec": None},
}

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


@dataclass
class ExportRequest:
    project_id: str
    clip_id: str
    preset: str = "douyin"
    subtitles: bool = True
    title_card: bool = True
    layout: Optional[str] = None  # 覆盖预设：blur / crop / smart / fit / none
    hook_text: Optional[str] = None  # 短视频画面上的短钩子；平台标题仍保留在 metadata


# ---------------------------------------------------------------- resolve ---
def list_presets() -> List[Dict[str, Any]]:
    return [{"key": k, **v} for k, v in PRESETS.items()]


def find_source_video(project_id: str) -> Path:
    from backend.core.path_utils import get_project_directory
    raw = get_project_directory(project_id) / "raw"
    for p in [raw / "input.mp4", raw / "input.mov", raw / "input.mkv", raw / "input.webm"]:
        if p.exists():
            return p
    vids = sorted(raw.glob("input.*"))
    if vids:
        return vids[0]
    raise FileNotFoundError(f"项目 {project_id} 没有源视频（raw/input.*）")


def find_source_srt(project_id: str) -> Optional[Path]:
    from backend.core.path_utils import get_project_directory
    project_dir = get_project_directory(project_id)
    for p in (project_dir / "raw" / "input.srt", project_dir / "metadata" / "input.srt"):
        if p.exists():
            return p
    found = list((project_dir / "metadata").glob("*.srt"))
    return found[0] if found else None


def load_clip_meta(project_id: str, clip_id: str) -> Dict[str, Any]:
    from backend.core.path_utils import get_project_directory
    path = get_project_directory(project_id) / "metadata" / "clips_metadata.json"
    if path.exists():
        clips = json.loads(path.read_text(encoding="utf-8"))
        for c in clips:
            if str(c.get("id")) == str(clip_id):
                # New Short metadata can be produced by Step 3 before Step 6
                # persists the final clip metadata. Merge it when available so
                # users can export immediately after an analysis rerun.
                short_path = get_project_directory(project_id) / "metadata" / "step3_high_score_clips.json"
                if not c.get("short_start_time") and short_path.exists():
                    try:
                        scored = json.loads(short_path.read_text(encoding="utf-8"))
                        match = next((x for x in scored if str(x.get("id")) == str(clip_id)), None)
                        if match:
                            for field in ("short_start_time", "short_end_time", "short_duration_sec", "duration_fit_score", "complete_thought", "short_hook", "short_publishable", "short_publish_rejection_reasons"):
                                if field in match:
                                    c[field] = match[field]
                    except (OSError, ValueError, TypeError):
                        pass
                return c
    raise FileNotFoundError(f"项目 {project_id} 没有切片 {clip_id}")


def resolve_cjk_font() -> Optional[Path]:
    candidates = [
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyh.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _escape_filter_path(p: Path) -> str:
    return str(p.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _format_hook_text(text: str, max_chars_per_line: int = 25, max_lines: int = 2) -> str:
    """Wrap a short visual hook so it cannot become a clipped one-line title."""
    clean = " ".join(str(text or "").replace("\n", " ").split()).strip()
    if not clean:
        return ""

    words = clean.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars_per_line and len(lines) < max_lines - 1:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)

    return "\n".join(lines[:max_lines])


def _load_srt_entries(project_id: str) -> List[Dict[str, Any]]:
    from backend.core.path_utils import get_project_directory
    from backend.utils.text_processor import TextProcessor
    project_dir = get_project_directory(project_id)
    chunks = load_srt_chunks(project_dir / "metadata")
    if chunks:
        return chunks
    srt = find_source_srt(project_id)
    if srt:
        return TextProcessor.parse_srt(srt)
    return []


# ---------------------------------------------------------------- ffmpeg ---
def _layout_filters(layout: str, w: Optional[int], h: Optional[int], source_aspect: Optional[float] = None) -> List[str]:
    if layout == "none" or not w or not h:
        return []
    if layout == "blur":
        return [
            f"[0:v]split=2[bg][fg]",
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=24[bg2]",
            f"[fg]scale={w}:-2[fg2]",
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2[base]",
        ]
    if layout == "crop":
        return [f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}[base]"]
    if layout == "smart":
        # A source that is already approximately 9:16 does not need a second
        # vertical canvas. Reframing it would duplicate its existing overlays.
        if source_aspect is not None and source_aspect <= 0.78:
            return []
        # Preserve the speaker while reserving a clean lower band for generated
        # captions. Some source clips already contain burned-in captions; they
        # cannot be removed by disabling an SRT track, so the foreground gets a
        # small configurable bottom crop. The blurred background still fills the
        # complete 9:16 canvas.
        try:
            crop_ratio = max(0.0, min(0.22, float(os.getenv("AUTOCLIP_FOREGROUND_BOTTOM_CROP_RATIO", "0.12"))))
        except (TypeError, ValueError):
            crop_ratio = 0.12
        crop_expr = f"crop=iw:ih*(1-{crop_ratio:.3f}):0:0,"
        return [
            f"[0:v]split=2[bg][fg]",
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},gblur=sigma=28[bg2]",
            f"[fg]{crop_expr}scale={w}:-2[fg2]",
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2[base]",
        ]
    if layout == "fit":
        return [f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black[base]"]
    return []


def _build_filter(req: ExportRequest, spec: Dict[str, Any], srt_path: Optional[Path],
                  title_path: Optional[Path], font: Optional[Path], ass_path: Optional[Path] = None,
                  source_aspect: Optional[float] = None) -> Optional[str]:
    layout = req.layout or spec["layout"]
    parts = _layout_filters(layout, spec.get("w"), spec.get("h"), source_aspect=source_aspect)
    last = "base" if parts else "0:v"
    subtitle_path = ass_path or srt_path
    if subtitle_path is not None:
        nxt = "sub"
        if ass_path is not None:
            parts.append(f"[{last}]subtitles='{_escape_filter_path(ass_path)}'[{nxt}]")
        else:
            style = "Fontsize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=48,Alignment=2"
            if font:
                style = "FontName=Noto Sans," + style
            parts.append(f"[{last}]subtitles='{_escape_filter_path(srt_path)}':force_style='{style}'[{nxt}]")
        last = nxt
    if title_path is not None and font is not None:
        nxt = "out"
        parts.append(
            f"[{last}]drawtext=fontfile='{_escape_filter_path(font)}':textfile='{_escape_filter_path(title_path)}'"
            f":reload=0:x=(w-text_w)/2:y=h*0.065:fontsize=50:fontcolor=white:borderw=3:bordercolor=black"
            f":box=1:boxcolor=black@0.45:boxborderw=16:line_spacing=8:enable='lt(t\\,2.8)'[{nxt}]"
        )
        last = nxt
    if not parts:
        return None
    # 最后一条没有输出标签时 ffmpeg 也能用，但我们都打了标签：把最后标签接到默认输出
    # filter_complex 最后一个 [tag] 需要 map
    return ";".join(parts), last


def export_clip(req: ExportRequest, progress_callback=None) -> Dict[str, Any]:
    """同步导出一条切片。幂等：同参数已存在直接返回。"""
    if req.preset not in PRESETS:
        raise ValueError(f"未知预设: {req.preset}（可选 {', '.join(PRESETS)}）")
    spec = PRESETS[req.preset]
    clip = load_clip_meta(req.project_id, req.clip_id)
    video = find_source_video(req.project_id)
    source_start = to_seconds(clip["start_time"])
    source_end = to_seconds(clip["end_time"])
    start, end = source_start, source_end
    source_probe = _probe(video)
    source_width = float(source_probe.get("width") or 0.0)
    source_height = float(source_probe.get("height") or 0.0)
    source_aspect = source_width / source_height if source_width and source_height else None
    already_vertical_source = bool(source_aspect is not None and source_aspect <= 0.78)
    warnings: List[str] = []
    vertical = req.preset in {"shorts", "tiktok", "douyin", "xiaohongshu"} and spec.get("h") == 1920

    # Phase 2: selected clips retain their original boundaries, while Shorts
    # exports can use an AI-recommended complete-thought range when validated.
    if vertical and clip.get("short_start_time") and clip.get("short_end_time"):
        try:
            candidate_start = to_seconds(clip["short_start_time"])
            candidate_end = to_seconds(clip["short_end_time"])
            if source_start <= candidate_start < candidate_end <= source_end and candidate_end - candidate_start <= 180:
                start, end = candidate_start, candidate_end
            else:
                warnings.append("AI 短视频时长建议未通过边界校验，使用原切片时长")
        except (TypeError, ValueError):
            warnings.append("AI 短视频时长建议格式无效，使用原切片时长")

    # Give the last spoken word a little breathing room in vertical Shorts.
    # This is intentionally applied before the preset duration cap.
    if vertical:
        try:
            end_padding = max(0.0, float(os.getenv("AUTOCLIP_SHORT_END_PADDING_SEC", "0.5")))
        except (TypeError, ValueError):
            end_padding = 0.5
        if end_padding:
            media_duration = float(source_probe.get("duration") or 0.0)
            end = min(end + end_padding, media_duration) if media_duration > 0 else end + end_padding

    duration = max(0.1, end - start)
    if spec.get("max_sec") and duration > spec["max_sec"]:
        duration = float(spec["max_sec"])
        warnings.append(f"按时长上限截到 {spec['max_sec']}s（{req.preset}）")

    title = str(clip.get("generated_title") or clip.get("title") or clip.get("outline") or f"Clip {req.clip_id}")
    hook_text = req.hook_text or clip.get("short_hook")
    if req.title_card:
        hook_text = _format_hook_text(hook_text or title)
    from backend.core.path_utils import get_project_directory
    out_dir = get_project_directory(req.project_id) / "output" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    # v8: bounded hook overlay replaces the old single-line title-card behavior.
    slug = f"{req.clip_id}_{req.preset}_v12"
    if not req.subtitles:
        slug += "_nosub"
    if not req.title_card:
        slug += "_notitle"
    if req.layout:
        slug += f"_{req.layout}"
    out_path = out_dir / f"{slug}.mp4"
    meta_path = out_dir / f"{slug}.json"

    if out_path.exists() and out_path.stat().st_size > 0:
        result = {"ok": True, "path": str(out_path), "cached": True, "preset": req.preset,
                  "clip_id": req.clip_id, "title": title, "duration_sec": round(duration, 2),
                  "warnings": warnings}
        return result

    font = resolve_cjk_font()
    if req.title_card and not font:
        warnings.append("没找到中文字体，已跳过标题卡")
    tmpdir = Path(tempfile.mkdtemp(prefix="ac-export-"))
    srt_file = None
    ass_file = None
    title_file = None
    try:
        entries: List[Dict[str, Any]] = []
        pages: List[Any] = []
        generate_subtitles = req.subtitles
        if vertical and already_vertical_source:
            skip_generated = os.getenv("AUTOCLIP_SKIP_GENERATED_CAPTIONS_ON_VERTICAL_SOURCE", "true").strip().lower() not in {"0", "false", "no", "off"}
            if skip_generated:
                generate_subtitles = False
                warnings.append("源视频已是竖屏，跳过再次烧录词级字幕以避免重复字幕")
        if generate_subtitles:
            entries = _load_srt_entries(req.project_id)
            body = slice_srt(entries, start, end)
            if body:
                # Vertical Shorts use only the new word-timed ASS layer. Do not
                # pass the source SRT into FFmpeg, otherwise the original
                # rolling/Chinese subtitle layer can appear above the captions.
                if not vertical:
                    srt_file = tmpdir / "clip.srt"
                    srt_file.write_text(body, encoding="utf-8")
                if vertical:
                    # YouTube's rolling SRT cues are not authoritative word
                    # timing. Generate word timestamps from the actual audio.
                    try:
                        from backend.utils.speech_recognizer import transcribe_word_timestamps
                        from backend.core.path_utils import get_project_directory
                        cache_path = (
                            get_project_directory(req.project_id) / "metadata"
                            / f"word_transcript_{req.clip_id}_{int(start * 1000)}_{int(end * 1000)}.json"
                        )
                        if cache_path.exists():
                            try:
                                words = json.loads(cache_path.read_text(encoding="utf-8"))
                            except (OSError, ValueError, TypeError):
                                words = []
                        else:
                            words = []
                        if not words:
                            caption_model = os.getenv("AUTOCLIP_CAPTION_WHISPER_MODEL", "tiny")
                            words = transcribe_word_timestamps(
                                video, start=start, end=end, model_name=caption_model, language="en"
                            )
                            cache_path.parent.mkdir(parents=True, exist_ok=True)
                            cache_path.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")
                        pages = build_word_caption_pages(words, start, end)
                        if pages:
                            ass_file = tmpdir / "shorts_v3.ass"
                            ass_file.write_text(
                                build_ass(
                                    pages,
                                    width=int(spec["w"]),
                                    height=int(spec["h"]),
                                    font_name="Noto Sans CJK SC",
                                    font_size=72,
                                    time_offset=start,
                                ),
                                encoding="utf-8",
                            )
                            logger.info("短视频字幕使用 %d 个真实词级时间点", len(words))
                        else:
                            warnings.append("Whisper 未产生词级字幕，短视频不烧字")
                            srt_file = None
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("词级字幕生成失败，拒绝回退到伪造词级时间: %s", exc)
                        warnings.append("词级 Whisper 字幕不可用，短视频不烧字")
                        srt_file = None
            else:
                warnings.append("没有可用字幕，成片不烧字")
        if req.title_card and font:
            title_file = tmpdir / "hook.txt"
            title_file.write_text(hook_text, encoding="utf-8")

        built = _build_filter(
            req,
            spec,
            srt_file,
            title_file if req.title_card else None,
            font,
            ass_path=ass_file,
            source_aspect=source_aspect,
        )
        ffmpeg = get_ffmpeg_path()
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{duration:.3f}"]
        maps: List[str] = []
        if built:
            graph, last = built
            cmd += ["-filter_complex", graph, "-map", f"[{last}]"]
        else:
            cmd += ["-map", "0:v:0"]
        cmd += ["-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                "-progress", "pipe:1", "-nostats", "-y", str(out_path)]
        logger.info("发布导出: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="ignore")
        stdout_lines = []
        if proc.stdout is not None:
            for line in proc.stdout:
                stdout_lines.append(line)
                if progress_callback and line.startswith("out_time_ms="):
                    try:
                        out_ms = float(line.split("=", 1)[1].strip())
                        ratio = min(1.0, max(0.0, out_ms / 1_000_000 / max(duration, 0.1)))
                        progress_callback(10 + ratio * 88)
                    except (ValueError, ZeroDivisionError):
                        pass
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        return_code = proc.wait()
        if return_code != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError((stderr or "".join(stdout_lines) or "ffmpeg 失败")[-800:])

        info = _probe(out_path)
        result = {
            "ok": True, "cached": False, "path": str(out_path), "preset": req.preset,
            "clip_id": req.clip_id, "project_id": req.project_id, "title": title,
            "hook_text": hook_text if req.title_card else None,
            "duration_sec": info.get("duration") or round(duration, 2),
            "source_duration_sec": round(source_end - source_start, 2),
            "short_duration_source": "ai_recommended" if vertical and clip.get("short_start_time") else "clip",
            "subtitle_engine": "ass_karaoke_v3" if ass_file is not None else ("srt" if srt_file is not None else None),
            "subtitle_pages": len(pages) if req.subtitles and vertical and ass_file is not None else 0,
            "width": info.get("width"), "height": info.get("height"),
            "font": str(font) if font else None, "warnings": warnings,
        }
        meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _probe(path: Path) -> Dict[str, Any]:
    try:
        cmd = [get_ffprobe_path(), "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)]
        raw = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="ignore")
        data = json.loads(raw)
        stream = (data.get("streams") or [{}])[0]
        return {
            "width": stream.get("width"),
            "height": stream.get("height"),
            "duration": round(float((data.get("format") or {}).get("duration") or 0), 2),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug(f"ffprobe 失败: {e}")
        return {}


# ---------------------------------------------------------------- jobs ---
def start_export(req: ExportRequest) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"job_id": job_id, "status": "queued", "percent": 0, "project_id": req.project_id, "clip_id": req.clip_id}
    t = threading.Thread(target=_run_job, args=(job_id, req), daemon=True, name=f"export-{job_id[:8]}")
    t.start()
    return {"ok": True, "job_id": job_id, "status": "queued"}


def _run_job(job_id: str, req: ExportRequest) -> None:
    with _jobs_lock:
        _jobs[job_id].update(status="running", percent=10)
    try:
        result = export_clip(req, progress_callback=lambda p: _update_job_percent(job_id, p))
        with _jobs_lock:
            _jobs[job_id].update(status="completed", percent=100, result=result)
    except Exception as e:  # noqa: BLE001
        logger.exception("发布导出失败")
        with _jobs_lock:
            _jobs[job_id].update(status="failed", percent=100, error=str(e)[:500])


def _update_job_percent(job_id: str, percent: float) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["percent"] = max(0, min(99, round(percent, 1)))


def get_export_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def export_many(project_id: str, clip_ids: Sequence[str], preset: str,
                subtitles: bool = True, title_card: bool = True) -> List[Dict[str, Any]]:
    out = []
    for cid in clip_ids:
        try:
            out.append(export_clip(ExportRequest(project_id, cid, preset, subtitles, title_card)))
        except Exception as e:  # noqa: BLE001
            out.append({"ok": False, "clip_id": cid, "error": str(e)[:400]})
    return out
