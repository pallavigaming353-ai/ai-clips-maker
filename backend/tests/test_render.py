import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from app.main import render, probe

@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RenderSmokeTest(unittest.TestCase):
    def test_captioned_video_renders(self):
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
        if " subtitles " not in filters.stdout:
            self.skipTest("FFmpeg subtitles/libass filter unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            subtitle = root / "caption.srt"
            subtitle.write_text("1\\n00:00:00,000 --> 00:00:01,500\\nनमस्ते दुनिया\\n\\n", encoding="utf-8")
            subprocess.run(["ffmpeg","-nostdin","-y","-f","lavfi","-i","color=c=blue:s=320x180:r=24:d=2","-f","lavfi","-i","anullsrc=r=44100:cl=stereo","-t","2","-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-shortest",str(source)], check=True, capture_output=True, timeout=60)
            self.assertGreater(probe(source), 1.5)
            for vertical in (True,False):
                with self.subTest(vertical=vertical):
                    target = root / ("portrait.mp4" if vertical else "landscape.mp4")
                    render(source, target, 0, 1, vertical, subtitle)
                    self.assertTrue(target.is_file())
                    self.assertGreater(target.stat().st_size, 0)
