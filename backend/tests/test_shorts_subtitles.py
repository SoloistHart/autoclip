"""Short-form subtitle segmentation and duration validation tests."""
from backend.services.shorts_subtitles import (
    build_ass,
    build_caption_pages,
    build_word_caption_pages,
    clamp_short_range,
    duration_range,
)


def _entries():
    return [
        {"start_time": "00:00:00,000", "end_time": "00:00:02,000", "text": "Trauma is not what happened to you."},
        {"start_time": "00:00:02,000", "end_time": "00:00:04,000", "text": "It is what happened inside of you."},
        {"start_time": "00:00:04,000", "end_time": "00:00:06,000", "text": "That distinction matters."},
    ]


def test_caption_pages_are_short_and_two_line():
    pages = build_caption_pages(_entries(), 0, 6)
    assert pages
    assert all(len(p.lines) == 2 for p in pages)
    assert all(p.end > p.start for p in pages)
    assert all(len(p.tokens) <= 7 for p in pages)


def test_caption_word_normalization_preserves_contractions_without_duplicate_punctuation():
    words = [
        {"word": "there’s", "start": 0.0, "end": 0.4},
        {"word": "really", "start": 0.4, "end": 0.8},
        {"word": "important", "start": 0.8, "end": 1.2},
    ]
    pages = build_word_caption_pages(words, 0, 2)
    text = " ".join(p.lines[0] + " " + p.lines[1] for p in pages)
    assert "there's" in text
    assert "there''s" not in text


def test_ass_has_real_karaoke_word_timing():
    words = [
        {"word": "this", "start": 0.00, "end": 0.25},
        {"word": "is", "start": 0.30, "end": 0.45},
        {"word": "really", "start": 0.50, "end": 0.90},
        {"word": "important", "start": 0.95, "end": 1.50},
    ]
    pages = build_word_caption_pages(words, 0, 2)
    ass = build_ass(pages)
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Style: Shorts" in ass
    assert ",360,1" in ass
    assert ass.count("Dialogue:") == len(pages)
    assert r"\k30" in ass
    assert r"\k45" in ass
    assert "this" in ass
    assert "is" in ass
    assert "really" in ass
    assert "important" in ass
    assert r"\N" in ass


def test_word_caption_pages_never_overlap_adjacent_phrase_events():
    words = [
        {"word": "So", "start": 32.94, "end": 33.00},
        {"word": "there's", "start": 33.00, "end": 33.30},
        {"word": "neglect", "start": 33.30, "end": 33.90},
        {"word": "and", "start": 33.90, "end": 34.90},
        {"word": "then", "start": 34.90, "end": 35.10},
        {"word": "there's", "start": 35.10, "end": 35.34},
        {"word": "Molly", "start": 35.34, "end": 35.60},
        {"word": "Codling", "start": 35.60, "end": 35.94},
    ]
    pages = build_word_caption_pages(words, 32.0, 37.0, max_words=5)
    assert len(pages) >= 2
    for previous, current in zip(pages, pages[1:]):
        assert previous.end < current.start
        assert current.start - previous.end >= 0.019


def test_word_caption_pages_preserve_audio_timing_and_break_on_pauses():
    words = [
        {"word": "this", "start": 1.00, "end": 1.20},
        {"word": "child", "start": 1.21, "end": 1.50},
        {"word": "has", "start": 1.51, "end": 1.70},
        {"word": "twenty", "start": 1.71, "end": 2.00},
        {"word": "four", "start": 2.01, "end": 2.20},
        {"word": "cushions", "start": 2.90, "end": 3.30},
    ]
    pages = build_word_caption_pages(words, 0, 4)
    assert pages[0].start == 1.0
    assert pages[0].end == 2.2
    assert pages[1].start == 2.9
    assert pages[1].tokens[0].start == 2.9


def test_overlapping_source_cues_keep_the_later_cue_start():
    entries = [
        {
            "start_time": "00:25:11,845",
            "end_time": "00:25:14,399",
            "text": "this child has 24 pillows around them",
        },
        {
            "start_time": "00:25:13,399",
            "end_time": "00:25:14,559",
            "text": "I'd be",
        },
        {
            "start_time": "00:25:14,460",
            "end_time": "00:25:16,868",
            "text": "interested to know. I am",
        },
    ]
    pages = build_caption_pages(entries, 1511.0, 1517.0)
    assert pages
    # The second cue must appear at its source start, not after cue 1's
    # original end. The previous implementation delayed it by ~1 second.
    second = next(p for p in pages if "I'd" in p.lines[0] or "I'd" in p.lines[1])
    assert second.start == 1513.399
    first = pages[0]
    assert first.end <= second.start
    assert all(p.end > p.start for p in pages)


def test_duration_ranges():
    assert duration_range("auto") == (30.0, 90.0)
    assert duration_range("15-30") == (15.0, 30.0)
    assert duration_range("90-180") == (90.0, 180.0)


def test_long_ai_range_is_narrowed_to_subtitle_boundary():
    clip = {
        "start_time": "00:00:00,000",
        "end_time": "00:05:00,000",
    }
    result = clamp_short_range(
        clip,
        "00:00:00,000",
        "00:05:00,000",
        _entries(),
        preference="auto",
    )
    # The fixture has no cue near 30–90s, so a complete boundary cannot be
    # produced; this is intentionally rejected rather than cutting mid-cue.
    assert result is None


def test_sentence_repair_moves_continuation_start_and_end_to_complete_thought():
    entries = [
        {"start_time": "00:00:00,000", "end_time": "00:00:04,000", "text": "I used to think consistency"},
        {"start_time": "00:00:04,000", "end_time": "00:00:08,000", "text": "was about posting every day,"},
        {"start_time": "00:00:08,000", "end_time": "00:00:12,000", "text": "but that is not the point."},
        {"start_time": "00:00:12,000", "end_time": "00:00:16,000", "text": "The real lesson is to keep learning."},
        {"start_time": "00:00:16,000", "end_time": "00:00:20,000", "text": "That takes more time than people expect."},
        {"start_time": "00:00:20,000", "end_time": "00:00:24,000", "text": "You need enough repetitions to see what works"},
        {"start_time": "00:00:24,000", "end_time": "00:00:28,000", "text": "Then you can adjust the process."},
        {"start_time": "00:00:28,000", "end_time": "00:00:32,000", "text": "That is where consistency matters."},
    ]
    clip = {"start_time": "00:00:00,000", "end_time": "00:00:32,000"}
    result = clamp_short_range(
        clip,
        "00:00:04,000",
        "00:00:23,000",
        entries,
        preference="15-30",
    )
    assert result is not None
    assert result["short_start_time"] == "00:00:00,000"
    assert result["short_end_time"] == "00:00:28,000"
    assert "extend_start_to_sentence" in result["short_boundary_ops"]
    assert "extend_end_to_sentence" in result["short_boundary_ops"]


def test_valid_ai_range_is_preserved_and_scored():
    entries = _entries() + [
        {"start_time": "00:00:06,000", "end_time": "00:00:36,000", "text": "A longer complete thought follows."},
    ]
    clip = {"start_time": "00:00:00,000", "end_time": "00:01:00,000"}
    result = clamp_short_range(clip, "00:00:00,000", "00:00:36,000", entries, preference="auto")
    assert result is not None
    assert 30 <= result["short_duration_sec"] <= 90
    assert result["duration_fit_score"] > 0
