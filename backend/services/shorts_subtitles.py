"""Short-form subtitle and duration helpers.

The export layer keeps source SRT intact, then derives a presentation-oriented
ASS track for vertical Shorts. Timing is inferred from SRT cue timing when
word-level timestamps are unavailable; the result is deterministic and never
rewrites spoken text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.pipeline.quality import to_seconds, to_srt_time


DURATION_RANGES: Dict[str, Tuple[float, float]] = {
    "auto": (30.0, 90.0),
    "15-30": (15.0, 30.0),
    "30-60": (30.0, 60.0),
    "60-90": (60.0, 90.0),
    "90-180": (90.0, 180.0),
}


@dataclass(frozen=True)
class CaptionToken:
    text: str
    start: float
    end: float
    confidence: Optional[float] = None


@dataclass(frozen=True)
class CaptionPage:
    start: float
    end: float
    lines: Tuple[str, str]
    tokens: Tuple[CaptionToken, ...]


def duration_range(preference: str = "auto", custom_seconds: float = 60.0) -> Tuple[float, float]:
    if preference == "custom":
        value = max(5.0, min(180.0, float(custom_seconds)))
        return (max(5.0, value - 15.0), min(180.0, value + 15.0))
    return DURATION_RANGES.get(preference, DURATION_RANGES["auto"])


def _clean_text(text: str) -> str:
    text = str(text or "").replace("\u200b", " ")
    # Whisper may alternate ASCII/typographic apostrophes between words.
    # Normalize only presentation punctuation; never rewrite the spoken token.
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"'{2,}", "'", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_word_text(text: str) -> str:
    """Normalize a single Whisper word for display without changing wording."""
    value = _clean_text(text)
    value = re.sub(r"^[,;:]+", "", value)
    value = re.sub(r"[,;:]+$", lambda m: m.group(0)[-1], value)
    return value.strip()


def _tokenize(text: str) -> List[str]:
    text = _clean_text(text)
    if not text:
        return []
    # Keep punctuation attached to the preceding/following lexical unit so
    # caption breaks remain readable.
    return re.findall(r"[^\s]+", text)


def _unit_width(token: str) -> int:
    # CJK glyphs are visually wider than Latin glyphs at the same font size.
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in token)


def _token_timing(tokens: Sequence[str], start: float, end: float) -> List[CaptionToken]:
    if not tokens:
        return []
    duration = max(0.01, end - start)
    weights = [max(1, _unit_width(t)) for t in tokens]
    total = float(sum(weights))
    out: List[CaptionToken] = []
    cursor = start
    for i, (token, weight) in enumerate(zip(tokens, weights)):
        nxt = end if i == len(tokens) - 1 else cursor + duration * (weight / total)
        out.append(CaptionToken(token, cursor, max(cursor + 0.01, nxt)))
        cursor = nxt
    return out


def _break_lines(tokens: Sequence[str], max_units: int = 24) -> Tuple[str, str]:
    if not tokens:
        return "", ""
    best = 0
    best_delta = 10**9
    units = [max(1, _unit_width(t)) for t in tokens]
    for i in range(1, len(tokens)):
        left, right = sum(units[:i]), sum(units[i:])
        if left <= max_units and right <= max_units:
            delta = abs(left - right)
            if delta < best_delta:
                best, best_delta = i, delta
    if not best:
        best = min(len(tokens), max(1, len(tokens) // 2))
    return " ".join(tokens[:best]), " ".join(tokens[best:])


def build_caption_pages(
    entries: Sequence[Dict[str, Any]],
    start: float,
    end: float,
    max_words: int = 7,
    max_units: int = 24,
    min_duration: float = 0.55,
    max_duration: float = 3.2,
) -> List[CaptionPage]:
    """Build readable pages while preserving the source cue start times.

    YouTube rolling captions commonly overlap: a later cue can begin before the
    previous cue's nominal end. The old implementation merged cues into a
    single stream and then forced every page to start after the previous page
    ended. That made captions visibly lag the speech. Here each source cue is
    segmented independently and each page is capped by the next page's start,
    so an overlapping cue replaces the previous caption at its real start time.
    """
    pages: List[CaptionPage] = []

    for entry in entries:
        try:
            cue_start = max(start, to_seconds(entry["start_time"]))
            cue_end = min(end, to_seconds(entry["end_time"]))
        except (KeyError, TypeError, ValueError):
            continue
        if cue_end <= cue_start:
            continue

        tokens = _token_timing(_tokenize(entry.get("text", "")), cue_start, cue_end)
        if not tokens:
            continue

        chunks: List[List[CaptionToken]] = []
        current: List[CaptionToken] = []
        units = 0
        for token in tokens:
            token_units = _unit_width(token.text)
            if current and (
                len(current) >= max_words
                or units + token_units > max_units * 2
            ):
                chunks.append(current)
                current = []
                units = 0
            current.append(token)
            units += token_units
        if current:
            chunks.append(current)

        for chunk in chunks:
            chunk_start = chunk[0].start
            chunk_end = chunk[-1].end
            if chunk_end - chunk_start < min_duration:
                chunk_end = min(cue_end, chunk_start + min_duration)
            if chunk_end - chunk_start > max_duration:
                chunk_end = chunk_start + max_duration
            words = [t.text for t in chunk]
            line1, line2 = _break_lines(words, max_units=max_units)
            pages.append(
                CaptionPage(
                    start=max(start, chunk_start),
                    end=min(end, max(cue_start + 0.05, chunk_end)),
                    lines=(line1, line2),
                    tokens=tuple(chunk),
                )
            )

    # Rolling captions may overlap in the source. Keep the next page's exact
    # start time and end the previous page there instead of delaying the next
    # page. This preserves the timing signal from the source SRT without
    # stacking two captions at the same screen position.
    normalized: List[CaptionPage] = []
    for index, page in enumerate(pages):
        next_start = pages[index + 1].start if index + 1 < len(pages) else end
        pe = min(page.end, next_start, end)
        ps = max(start, page.start)
        if pe <= ps:
            continue
        normalized.append(CaptionPage(ps, pe, page.lines, page.tokens))
    return normalized


def _ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\\{").replace("}", r"\\}")


def _ass_color(rgb: str) -> str:
    rgb = rgb.lstrip("#")
    if len(rgb) != 6:
        rgb = "FFFFFF"
    r, g, b = rgb[0:2], rgb[2:4], rgb[4:6]
    return f"&H00{b}{g}{r}"


def _ass_time(sec: float) -> str:
    cs = int(round(max(0.0, sec) * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def build_word_caption_pages(
    words: Sequence[Dict[str, Any]],
    start: float,
    end: float,
    max_words: int = 5,
    max_units: int = 24,
    max_duration: float = 2.8,
    pause_break: float = 0.45,
) -> List[CaptionPage]:
    """Group authoritative word timestamps into short-form phrase captions."""
    tokens: List[CaptionToken] = []
    for item in words:
        try:
            ws = max(start, float(item["start"]))
            we = min(end, float(item["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        text = _normalize_word_text(item.get("word", item.get("text", "")))
        if not text or we <= ws:
            continue
        tokens.append(CaptionToken(text, ws, we, item.get("confidence")))
    tokens.sort(key=lambda t: (t.start, t.end))

    pages: List[CaptionPage] = []
    current: List[CaptionToken] = []
    units = 0
    for token in tokens:
        pause = token.start - current[-1].end if current else 0.0
        punctuation_break = bool(re.search(r"[.!?;:]$", current[-1].text)) if current else False
        token_units = _unit_width(token.text)
        projected_duration = token.end - current[0].start if current else 0.0
        should_break = bool(current) and (
            len(current) >= max_words
            or units + token_units > max_units
            or projected_duration > max_duration
            or pause >= pause_break
            or punctuation_break
        )
        if should_break:
            pages.append(_make_word_page(current, start, end, max_units))
            current = []
            units = 0
        current.append(token)
        units += token_units
    if current:
        pages.append(_make_word_page(current, start, end, max_units))

    # ASS event boundaries can behave inclusively at the exact centisecond
    # where one event ends and the next begins. Leave a tiny deterministic gap
    # so adjacent phrase events can never render on top of each other for one
    # frame. This is especially important when Whisper places words exactly at
    # the previous phrase's end time.
    normalized: List[CaptionPage] = []
    boundary_gap = 0.02
    for index, page in enumerate(pages):
        page_end = page.end
        if index + 1 < len(pages):
            next_start = pages[index + 1].start
            page_end = min(page_end, next_start - boundary_gap)
        if page_end <= page.start:
            continue
        normalized.append(
            CaptionPage(page.start, page_end, page.lines, page.tokens)
        )
    return normalized


def _make_word_page(tokens: Sequence[CaptionToken], start: float, end: float, max_units: int) -> CaptionPage:
    words = [t.text for t in tokens]
    line1, line2 = _break_lines(words, max_units=max_units)
    page_start = max(start, tokens[0].start)
    page_end = min(end, max(tokens[-1].end, page_start + 0.08))
    return CaptionPage(page_start, page_end, (line1, line2), tuple(tokens))


def build_ass(
    pages: Sequence[CaptionPage],
    width: int = 1080,
    height: int = 1920,
    font_name: str = "Noto Sans",
    font_size: int = 72,
    accent_rgb: str = "FFD54A",
    time_offset: float = 0.0,
) -> str:
    """Build ASS with real word-timed karaoke highlighting."""
    accent = _ass_color(accent_rgb)
    white = _ass_color("FFFFFF")
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Shorts,{font_name},{font_size},{accent},{white},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,90,90,360,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = [header]
    for page in pages:
        tokens = list(page.tokens)
        if not tokens:
            continue
        first_line_words = len(page.lines[0].split()) if page.lines[0] else 0
        text_parts: List[str] = []
        cursor = page.start
        for index, token in enumerate(tokens):
            if index == first_line_words:
                text_parts.append(r"\N")
            next_start = tokens[index + 1].start if index + 1 < len(tokens) else page.end
            duration_cs = max(1, int(round(max(0.01, next_start - cursor) * 100)))
            text_parts.append("{" + f"\\k{duration_cs}" + "}" + _ass_escape(token.text))
            text_parts.append(" ")
            cursor = next_start
        text = "".join(text_parts).rstrip()
        start_time = page.start - time_offset
        end_time = page.end - time_offset
        if end_time <= start_time:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(start_time)},{_ass_time(end_time)},Shorts,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def slice_srt(entries: Sequence[Dict[str, Any]], start: float, end: float) -> str:
    lines: List[str] = []
    idx = 1
    for entry in entries:
        try:
            s, e = to_seconds(entry["start_time"]), to_seconds(entry["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if e <= start or s >= end:
            continue
        ns, ne = max(0.0, s - start), min(end, e) - start
        text = _clean_text(entry.get("text", ""))
        if not text:
            continue
        lines.append(f"{idx}\n{to_srt_time(ns)} --> {to_srt_time(ne)}\n{text}\n")
        idx += 1
    return "\n".join(lines)


def _is_sentence_end(text: str) -> bool:
    return bool(re.search(r"[.!?…][\"'”’»)]*$", _clean_text(text)))


def _sentence_boundary_indices(
    entries: Sequence[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
) -> List[Tuple[float, float, int]]:
    boundaries: List[Tuple[float, float, int]] = []
    for index, entry in enumerate(entries):
        try:
            start = to_seconds(entry["start_time"])
            end = to_seconds(entry["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if end < clip_start or start > clip_end:
            continue
        boundaries.append((start, end, index))
    return boundaries


def _repair_sentence_range(
    start: float,
    end: float,
    entries: Sequence[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    max_duration: float,
) -> Tuple[Optional[float], Optional[float], List[str]]:
    """Repair starts/ends that land inside a spoken thought.

    We only move to existing subtitle cue boundaries. A start is moved
    backwards to the nearest sentence boundary when its cue looks like a
    continuation; an end is moved forwards until the current thought ends.
    If repair would exceed the requested maximum duration, the range is
    rejected instead of producing a chopped sentence.
    """
    cues = _sentence_boundary_indices(entries, clip_start, clip_end)
    if not cues:
        return start, end, []

    start_index = min(range(len(cues)), key=lambda i: abs(cues[i][0] - start))
    end_index = min(range(len(cues)), key=lambda i: abs(cues[i][1] - end))
    ops: List[str] = []

    # Move a continuation start back to the nearest preceding sentence start.
    while start_index > 0:
        entry = entries[cues[start_index][2]]
        previous = entries[cues[start_index - 1][2]]
        text = _clean_text(entry.get("text", ""))
        previous_text = _clean_text(previous.get("text", ""))
        if _is_sentence_end(previous_text) or text[:1].isupper():
            break
        start_index -= 1
        ops.append("extend_start_to_sentence")

    repaired_start = max(clip_start, cues[start_index][0])

    # Move an unfinished end forward to a sentence boundary.
    while end_index + 1 < len(cues):
        entry = entries[cues[end_index][2]]
        text = _clean_text(entry.get("text", ""))
        next_entry = entries[cues[end_index + 1][2]]
        next_text = _clean_text(next_entry.get("text", ""))
        gap = cues[end_index + 1][0] - cues[end_index][1]
        if _is_sentence_end(text) or gap >= 0.75:
            break
        # Avoid treating a new capitalized cue as proof that the previous
        # sentence ended; punctuation/gap remains the stronger signal.
        if next_text and next_text[:1].isupper() and _is_sentence_end(text):
            break
        end_index += 1
        ops.append("extend_end_to_sentence")

    repaired_end = min(clip_end, cues[end_index][1])
    if repaired_end <= repaired_start:
        return None, None, ops
    if repaired_end - repaired_start > max_duration + 1e-6:
        return None, None, ops + ["sentence_repair_exceeded_max_duration"]

    return repaired_start, repaired_end, ops


def clamp_short_range(
    clip: Dict[str, Any],
    start_value: Any,
    end_value: Any,
    entries: Sequence[Dict[str, Any]],
    preference: str = "auto",
    custom_seconds: float = 60.0,
) -> Optional[Dict[str, Any]]:
    """Validate an AI-proposed Short range, snap it to SRT boundaries, and
    repair starts/ends that cut through a spoken thought."""
    try:
        clip_start = to_seconds(clip["start_time"])
        clip_end = to_seconds(clip["end_time"])
        proposed_start = to_seconds(str(start_value))
        proposed_end = to_seconds(str(end_value))
    except (KeyError, TypeError, ValueError):
        return None
    lo, hi = duration_range(preference, custom_seconds)
    proposed_start = max(clip_start, proposed_start)
    proposed_end = min(clip_end, proposed_end)
    if proposed_end <= proposed_start:
        return None
    duration = proposed_end - proposed_start
    # Long model ranges are allowed here because they can still be narrowed
    # to the requested Short range using real subtitle boundaries.
    # Snap only to real subtitle boundaries. This avoids mid-word/mid-sentence
    # cuts even when the model gives approximate timestamps.
    starts: List[float] = []
    ends: List[float] = []
    for entry in entries:
        try:
            s, e = to_seconds(entry["start_time"]), to_seconds(entry["end_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if clip_start - 3 <= s <= clip_end + 3:
            starts.append(s)
        if clip_start - 3 <= e <= clip_end + 3:
            ends.append(e)
    if starts:
        proposed_start = min(starts, key=lambda x: abs(x - proposed_start))
    if ends:
        proposed_end = min(ends, key=lambda x: abs(x - proposed_end))
    if proposed_end <= proposed_start:
        return None

    repaired_start, repaired_end, boundary_ops = _repair_sentence_range(
        proposed_start,
        proposed_end,
        entries,
        clip_start,
        clip_end,
        hi,
    )
    if repaired_start is None or repaired_end is None:
        return None
    proposed_start, proposed_end = repaired_start, repaired_end
    duration = proposed_end - proposed_start

    # If the model overshot the requested range, keep the natural start and
    # find the nearest valid subtitle boundary near the target end.
    if duration > hi:
        target_end = proposed_start + hi
        valid_ends: List[float] = []
        for index, entry in enumerate(entries):
            try:
                cue_start = to_seconds(entry["start_time"])
                cue_end = to_seconds(entry["end_time"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (proposed_start + lo <= cue_end <= proposed_start + hi):
                continue
            natural_end = _is_sentence_end(entry.get("text", ""))
            if not natural_end and index + 1 < len(entries):
                try:
                    next_start = to_seconds(entries[index + 1]["start_time"])
                    natural_end = next_start - cue_end >= 0.75
                except (KeyError, TypeError, ValueError):
                    pass
            if natural_end:
                valid_ends.append(cue_end)

        if not valid_ends:
            return None
        proposed_end = min(valid_ends, key=lambda x: abs(x - target_end))
        duration = proposed_end - proposed_start
    if duration < min(lo, 180.0) and clip_end - clip_start >= lo:
        return None
    return {
        "short_start_time": to_srt_time(proposed_start),
        "short_end_time": to_srt_time(proposed_end),
        "short_duration_sec": round(duration, 2),
        "short_duration_source": "ai_recommended",
        "short_boundary_ops": boundary_ops,
        "short_natural_start": not any(op == "extend_start_to_sentence" for op in boundary_ops),
        "short_natural_end": not any(op == "extend_end_to_sentence" for op in boundary_ops),
        "duration_fit_score": round(
            max(0.0, 1.0 - abs(duration - ((lo + hi) / 2)) / max(1.0, hi - lo)),
            2,
        ),
    }
