import json
from pathlib import Path

import pytest

pytest.importorskip("PIL")  # only the demo-video tool needs Pillow

from tools import make_demo_video as mdv  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / "tools" / "demo_shots.example.json"


def write(tmp_path, data):
    p = tmp_path / "shots.json"
    p.write_text(json.dumps(data))
    return p


def base():
    return {
        "title": {"text": "T", "sub": "s", "seconds": 2},
        "clips": [{"file": "a.mkv", "start": 1, "end": 5, "caption": "first"},
                  {"file": "b.mkv", "start": 0, "end": 3.5, "caption": "second"}],
        "end": {"text": "E", "seconds": 2},
    }


def test_example_fits_the_30_second_rule():
    shots = mdv.load_shot_list(EXAMPLE)
    assert shots.max_seconds == 30
    assert shots.seconds <= 30
    assert all(c.caption for c in shots.clips)


def test_paths_are_relative_to_the_shot_list(tmp_path):
    shots = mdv.load_shot_list(write(tmp_path, base()))
    assert shots.clips[0].file == tmp_path / "a.mkv"
    assert shots.output == tmp_path / "luna_atlas_demo.mp4"
    assert shots.seconds == pytest.approx(2 + 4 + 3.5 + 2)


def test_over_the_limit_is_refused(tmp_path):
    data = base()
    data["clips"][0]["end"] = 30
    with pytest.raises(mdv.ShotListError, match="over the 30 s limit"):
        mdv.load_shot_list(write(tmp_path, data))


@pytest.mark.parametrize("change, message", [
    ({"caption": ""}, "caption is required"),
    ({"end": 1}, "must be after start"),
    ({"start": -1}, "must be after start"),
])
def test_bad_clips_are_refused(tmp_path, change, message):
    data = base()
    data["clips"][0].update(change)
    with pytest.raises(mdv.ShotListError, match=message):
        mdv.load_shot_list(write(tmp_path, data))


def test_missing_field_is_named(tmp_path):
    data = base()
    del data["clips"][1]["end"]
    with pytest.raises(mdv.ShotListError, match="clip 2: missing 'end'"):
        mdv.load_shot_list(write(tmp_path, data))


def test_srt_follows_the_final_clock(tmp_path):
    srt = mdv.srt_text(mdv.load_shot_list(write(tmp_path, base())))
    blocks = srt.strip().split("\n\n")
    assert len(blocks) == 4
    assert blocks[0].splitlines()[1] == "00:00:00,000 --> 00:00:02,000"
    assert blocks[1].splitlines()[1:] == ["00:00:02,000 --> 00:00:06,000", "first"]
    assert blocks[2].splitlines()[1:] == ["00:00:06,000 --> 00:00:09,500", "second"]
    assert blocks[3].splitlines()[1] == "00:00:09,500 --> 00:00:11,500"


def test_srt_time_format():
    assert mdv.srt_time(3723.0456) == "01:02:03,046"
