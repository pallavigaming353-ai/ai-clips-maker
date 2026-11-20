"""End-to-end FFmpeg smoke test for hosted NeonClipping layouts (no network or AI model)."""
import json
import subprocess
import tempfile
from pathlib import Path
from app.main import render

def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)

with tempfile.TemporaryDirectory() as temp:
    folder = Path(temp)
    source = folder / "source.mp4"
    srt = folder / "captions.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nHello NeonClipping!\n", encoding="utf-8")
    run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "2", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", str(source))
    for layout in ("fill", "blur"):
        target = folder / (layout + ".mp4")
        render(source, target, 0, 2, True, srt, layout)
        assert target.is_file() and target.stat().st_size > 1000, layout
        probe = json.loads(run("ffprobe", "-v", "error", "-show_streams",
                               "-of", "json", str(target)).stdout)
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        assert (video["width"], video["height"]) == (1080, 1920), video
        assert any(s["codec_type"] == "audio" for s in probe["streams"])
        print(f"{layout}: rendered {target.stat().st_size} bytes, 1080x1920, with audio")
