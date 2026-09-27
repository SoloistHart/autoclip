"""Step 6 automatic Shorts quality gate tests."""
import json
from pathlib import Path

from backend.pipeline import step6_video as mod


def _clip(clip_id, publishable=True):
    return {
        "id": str(clip_id),
        "start_time": "00:00:00,000",
        "end_time": "00:00:45,000",
        "generated_title": f"Title {clip_id}",
        "short_hook": f"HOOK {clip_id}",
        "complete_thought": publishable,
        "hook_score": 0.9,
        "standalone_score": 0.9,
        "entry_point_score": 0.9,
        "payoff_score": 0.9,
        "ending_score": 0.9,
        "short_form_score": 0.9,
        "short_start_time": "00:00:00,000",
        "short_end_time": "00:00:45,000",
        "short_duration_sec": 45,
    }


def test_step6_auto_publish_skips_quality_failures(tmp_path, monkeypatch):
    clips_path = tmp_path / "clips.json"
    collections_path = tmp_path / "collections.json"
    output_dir = tmp_path / "output"
    clips_dir = tmp_path / "clips"
    collections_dir = tmp_path / "collections"
    metadata_dir = tmp_path / "metadata"
    clips_path.write_text(json.dumps([_clip("1", publishable=False), _clip("2", publishable=True)]), encoding="utf-8")
    collections_path.write_text("[]", encoding="utf-8")

    class FakeGenerator:
        def __init__(self, clips_dir=None, collections_dir=None, metadata_dir=None, progress_callback=None):
            self.metadata_dir = Path(metadata_dir)
            self.progress_callback = progress_callback

        def generate_clips(self, clips_with_titles, input_video):
            paths = []
            for clip in clips_with_titles:
                path = Path(clips_dir) / f"{clip['id']}_raw.mp4"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                paths.append(path)
            return paths

        def generate_collections(self, collections_data):
            return []

        def save_clip_metadata(self, clips_with_titles, output_path=None):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(json.dumps(clips_with_titles), encoding="utf-8")

        def save_collection_metadata(self, collections_data, output_path=None):
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(json.dumps(collections_data), encoding="utf-8")

    calls = []

    def fake_export(req, progress_callback=None):
        calls.append(req)
        return {"ok": True, "clip_id": req.clip_id, "hook_text": req.hook_text}

    monkeypatch.setattr(mod, "VideoGenerator", FakeGenerator)
    monkeypatch.setattr("backend.services.publish_export.export_clip", fake_export)
    monkeypatch.setenv("AUTOCLIP_AUTO_PUBLISH_SHORTS", "true")

    result = mod.run_step6_video(
        clips_path,
        collections_path,
        tmp_path / "input.mp4",
        output_dir=output_dir,
        clips_dir=str(clips_dir),
        collections_dir=str(collections_dir),
        metadata_dir=str(metadata_dir),
    )

    assert result["final_exports_generated"] == 1
    assert result["final_exports_skipped"] == 1
    assert result["skipped_short_exports"][0]["clip_id"] == "1"
    assert [c.clip_id for c in calls] == ["2"]
    assert calls[0].hook_text == "HOOK 2"
