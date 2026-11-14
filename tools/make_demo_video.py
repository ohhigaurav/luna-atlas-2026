#!/usr/bin/env python3
"""Cut the 30-second Space Apps demo video from short screen recordings, with no video editor.

Space Apps rules (Project Submission Guide, checked 9 Nov 2026): the demo video is at most
30 seconds, longer projects are not eligible for Global Judging, and video demos must have
English subtitles. This tool enforces the 30 s limit and burns each shot's caption into the
picture (so the subtitles cannot get lost on upload); it also writes a matching .srt file.

You record a few short clips (OBS or any screen recorder), write down where each good part
starts and ends, and list them in a shot list (see tools/demo_shots.example.json). Then:

    python3 tools/make_demo_video.py ~/Videos/luna/shots.json --frames   # stills to check
    python3 tools/make_demo_video.py ~/Videos/luna/shots.json            # the video

Needs ffmpeg/ffprobe on PATH and Pillow. Clip paths in the shot list are relative to the
shot list's folder. Output: <output>.mp4 (1920x1080, 30 fps, H.264, no sound) and <output>.srt.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
FADE_S = 0.25
ENCODE = ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(FPS)]
BG = (11, 13, 18)
FG = (240, 242, 247)
MUTED = (160, 168, 184)
FONT_CANDIDATES = [
    "/usr/share/fonts/TTF/DejaVuSans.ttf",  # Arch / EndeavourOS (ttf-dejavu)
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",  # Arch (noto-fonts)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian / Ubuntu
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
]


class ShotListError(ValueError):
    pass


@dataclass(frozen=True)
class Card:
    """A title or end card. With a file, the text sits over that footage under a dark veil."""
    text: str
    sub: str
    seconds: float
    file: Path | None = None
    start: float = 0.0


@dataclass(frozen=True)
class Clip:
    file: Path
    start: float
    end: float
    caption: str

    @property
    def seconds(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class ShotList:
    output: Path
    max_seconds: float
    title: Card | None
    clips: tuple[Clip, ...]
    end: Card | None

    def parts(self) -> list[Card | Clip]:
        return [p for p in (self.title, *self.clips, self.end) if p is not None]

    @property
    def seconds(self) -> float:
        return sum(p.seconds for p in self.parts())


def _card(raw: dict | None, name: str, base: Path) -> Card | None:
    if raw is None:
        return None
    seconds = float(raw.get("seconds", 2.5))
    if not raw.get("text") or seconds <= 0:
        raise ShotListError(f"{name}: needs text and seconds > 0")
    start = float(raw.get("start", 0.0))
    if start < 0:
        raise ShotListError(f"{name}: start must be 0 or more")
    file = (base / raw["file"]).expanduser() if raw.get("file") else None
    return Card(str(raw["text"]), str(raw.get("sub", "")), seconds, file, start)


def load_shot_list(path: Path) -> ShotList:
    """Read and check a shot list; raise ShotListError on anything that would break the cut."""
    raw = json.loads(path.read_text())
    base = path.parent
    clips = []
    for i, c in enumerate(raw.get("clips", []), 1):
        try:
            start, end = float(c["start"]), float(c["end"])
            clip = Clip((base / c["file"]).expanduser(), start, end, str(c.get("caption", "")).strip())
        except KeyError as exc:
            raise ShotListError(f"clip {i}: missing {exc}") from None
        if start < 0 or end <= start:
            raise ShotListError(f"clip {i}: end ({end}) must be after start ({start})")
        if not clip.caption:
            raise ShotListError(f"clip {i}: a caption is required (English subtitles are mandatory)")
        clips.append(clip)
    if not clips:
        raise ShotListError("no clips")
    shots = ShotList(
        output=(base / raw.get("output", "luna_atlas_demo.mp4")).expanduser(),
        max_seconds=float(raw.get("max_seconds", 30)),
        title=_card(raw.get("title"), "title", base),
        clips=tuple(clips),
        end=_card(raw.get("end"), "end", base),
    )
    if shots.seconds > shots.max_seconds + 1e-9:
        raise ShotListError(
            f"planned length {shots.seconds:.2f} s is over the {shots.max_seconds:g} s limit: "
            "shorten clips (end - start) or the title/end cards"
        )
    return shots


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt_text(shots: ShotList) -> str:
    """Subtitles for every part, timed on the final video's clock."""
    lines, t, n = [], 0.0, 0
    for part in shots.parts():
        text = part.caption if isinstance(part, Clip) else "\n".join(x for x in (part.text, part.sub) if x)
        n += 1
        lines.append(f"{n}\n{srt_time(t)} --> {srt_time(t + part.seconds)}\n{text}\n")
        t += part.seconds
    return "\n".join(lines)


def find_font(size: int) -> ImageFont.ImageFont:
    for p in FONT_CANDIDATES:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    try:
        hit = subprocess.run(["fc-match", "-f", "%{file}", "sans"], capture_output=True, text=True, check=False)
        if hit.stdout and Path(hit.stdout).is_file():
            return ImageFont.truetype(hit.stdout, size)
    except FileNotFoundError:
        pass
    return ImageFont.load_default(size)


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width or not line:
                line = trial
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def caption_overlay(text: str, path: Path) -> None:
    """Transparent 1920x1080 PNG with the caption on a dark band at the bottom."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = find_font(46)
    lines = wrap(d, text, font, W - 240)
    line_h = 60
    band_h = line_h * len(lines) + 48
    d.rectangle([0, H - band_h, W, H], fill=(0, 0, 0, 175))
    y = H - band_h + 24
    for line in lines:
        d.text((W / 2, y), line, font=font, fill=FG, anchor="ma")
        y += line_h
    img.save(path)


def card_image(card: Card, path: Path) -> None:
    """The card's text: on a plain background, or on a see-through veil when it has footage."""
    img = Image.new("RGBA", (W, H), (*BG, 165) if card.file else (*BG, 255))
    d = ImageDraw.Draw(img)
    big, small = find_font(110), find_font(48)
    d.text((W / 2, H / 2 - 40), card.text, font=big, fill=FG, anchor="ms")
    y = H / 2 + 50
    for line in wrap(d, card.sub, small, W - 300) if card.sub else []:
        d.text((W / 2, y), line, font=small, fill=FG if card.file else MUTED, anchor="ma")
        y += 64
    img.save(path)


def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stderr[-3000:])
        raise SystemExit(f"ffmpeg failed: {' '.join(cmd[:6])} …")


def probe_seconds(path: Path) -> float:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(res.stdout.strip())


def fades(seconds: float) -> str:
    return f"fade=t=in:st=0:d={FADE_S},fade=t=out:st={seconds - FADE_S:.3f}:d={FADE_S}"


def clip_graph(seconds: float, with_fades: bool = True) -> str:
    fit = (
        f"[0:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[v];[v][1:v]overlay=0:0,format=yuv420p"
    )
    return fit + ("," + fades(seconds) if with_fades else "")


def render_part(part: Card | Clip, work: Path, out: Path) -> None:
    tmp = out.with_name(out.stem + ".part.mp4")
    if isinstance(part, Card) and part.file is None:
        png = work / (out.stem + ".png")
        card_image(part, png)
        vf = f"format=yuv420p,loop=-1:1,trim=duration={part.seconds:.3f},{fades(part.seconds)}"
        run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", str(png), "-vf", vf, *ENCODE, "-an", str(tmp)])
    elif isinstance(part, Card):
        png = work / (out.stem + ".png")
        card_image(part, png)
        run([
            "ffmpeg", "-y", "-v", "error", "-ss", f"{part.start:.3f}", "-t", f"{part.seconds:.3f}",
            "-i", str(part.file), "-i", str(png), "-filter_complex", clip_graph(part.seconds),
            *ENCODE, "-an", str(tmp),
        ])
    else:
        cap = work / (out.stem + ".caption.png")
        caption_overlay(part.caption, cap)
        run([
            "ffmpeg", "-y", "-v", "error", "-ss", f"{part.start:.3f}", "-t", f"{part.seconds:.3f}",
            "-i", str(part.file), "-i", str(cap), "-filter_complex", clip_graph(part.seconds),
            *ENCODE, "-an", str(tmp),
        ])
    tmp.rename(out)


def write_frames(shots: ShotList, folder: Path) -> list[Path]:
    """One still per part (a clip's middle frame with its caption) to check before the full cut."""
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        for i, part in enumerate(shots.parts(), 1):
            out = folder / f"frame_{i:02d}.jpg"
            if isinstance(part, Card) and part.file is None:
                png = work / f"{i}.png"
                card_image(part, png)
                Image.open(png).convert("RGB").save(out, quality=92)
            else:
                cap = work / f"{i}.caption.png"
                if isinstance(part, Card):
                    card_image(part, cap)
                else:
                    caption_overlay(part.caption, cap)
                mid = part.start + part.seconds / 2
                run([
                    "ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.3f}", "-i", str(part.file), "-i", str(cap),
                    "-filter_complex", clip_graph(part.seconds, with_fades=False), "-frames:v", "1",
                    "-q:v", "2", str(out),
                ])
            made.append(out)
    return made


def build(shots: ShotList) -> Path:
    for part in shots.parts():
        if part.file is None:
            continue
        if not part.file.is_file():
            raise SystemExit(f"clip not found: {part.file}")
        have = probe_seconds(part.file)
        end = part.start + part.seconds
        if end > have + 0.05:
            raise SystemExit(f"{part.file.name}: end {end:g} s is past the recording's length ({have:.2f} s)")
    shots.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        files = []
        for i, part in enumerate(shots.parts(), 1):
            out = work / f"part_{i:02d}.mp4"
            print(f"  part {i}: {part.seconds:.2f} s", flush=True)
            render_part(part, work, out)
            files.append(out)
        listing = work / "list.txt"
        listing.write_text("".join(f"file '{f}'\n" for f in files))
        tmp = shots.output.with_name(shots.output.stem + ".part.mp4")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
             "-movflags", "+faststart", str(tmp)])
        tmp.rename(shots.output)
    shots.output.with_suffix(".srt").write_text(srt_text(shots))
    return shots.output


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("shots", type=Path, help="shot list JSON (see tools/demo_shots.example.json)")
    ap.add_argument("--frames", action="store_true", help="only write one still per part, to check captions")
    args = ap.parse_args(argv)
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} not found: on EndeavourOS run  sudo pacman -S ffmpeg")
    try:
        shots = load_shot_list(args.shots.expanduser())
    except ShotListError as exc:
        raise SystemExit(f"shot list: {exc}") from None
    print(f"planned length {shots.seconds:.2f} s (limit {shots.max_seconds:g} s), {len(shots.clips)} clips")
    if args.frames:
        folder = shots.output.parent / "frames"
        for f in write_frames(shots, folder):
            print(f"  {f}")
        print("Open these and check the captions read well, then run again without --frames.")
        return 0
    out = build(shots)
    got = probe_seconds(out)
    print(f"wrote {out} ({got:.2f} s) and {out.with_suffix('.srt')}")
    if got > shots.max_seconds + 0.1:
        print(f"WARNING: {got:.2f} s is over the {shots.max_seconds:g} s limit", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
