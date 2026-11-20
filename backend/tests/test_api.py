import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import main

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_youtube_url_validation(self):
        self.assertTrue(main.is_youtube_url("https://www.youtube.com/watch?v=abc123def45"))
        self.assertTrue(main.is_youtube_url("https://youtu.be/abc123def45"))
        self.assertFalse(main.is_youtube_url("http://youtube.com/watch?v=abc123def45"))
        self.assertFalse(main.is_youtube_url("https://youtube.com.evil.example/watch?v=abc123def45"))
        self.assertFalse(main.is_youtube_url("https://youtube.com:444/watch?v=abc123def45"))
        self.assertFalse(main.is_youtube_url("https://www.youtube.com/playlist?list=PL123"))
        self.assertFalse(main.is_youtube_url("https://www.youtube.com/watch?v=abc123def45&list=PL123"))
        self.assertTrue(main.is_youtube_url("https://www.youtube.com/shorts/abc123def45"))

    def test_youtube_canonicalization(self):
        self.assertEqual(
            main.canonical_youtube_url("https://youtu.be/abc123def45?t=90"),
            "https://www.youtube.com/watch?v=abc123def45",
        )
        self.assertEqual(
            main.canonical_youtube_url("https://www.youtube.com/shorts/abc123def45?feature=share"),
            "https://www.youtube.com/watch?v=abc123def45",
        )
        with self.assertRaises(ValueError):
            main.canonical_youtube_url("https://www.youtube.com/playlist?list=PL123")

    def test_youtube_link_job_invalid_duration(self):
        response = self.client.post("/api/jobs/from-link", data={"url": "https://youtu.be/abc123def45", "lengths": "999"})
        self.assertEqual(response.status_code, 422)

    def test_youtube_import_uses_single_mp4(self):
        class FakeDownloader:
            def __init__(self, options):
                self.options = options
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def extract_info(self, url, download=False):
                return {"duration": 120, "id": "abc123def45"}
            def download(self, urls):
                Path(self.options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"fake mp4")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "source.mp4"
            with patch("yt_dlp.YoutubeDL", FakeDownloader):
                main.import_youtube_video("https://youtu.be/abc123def45", target)
            self.assertEqual(target.read_bytes(), b"fake mp4")

    def test_youtube_import_rejects_long_video(self):
        class FakeDownloader:
            def __init__(self, options): pass
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def extract_info(self, url, download=False): return {"duration": 20000}
        with tempfile.TemporaryDirectory() as directory:
            with patch("yt_dlp.YoutubeDL", FakeDownloader):
                with self.assertRaises(ValueError):
                    main.import_youtube_video("https://youtu.be/abc123def45", Path(directory) / "source.mp4")

    def test_link_pipeline_produces_registered_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            job_id = "integrationtest"
            folder = Path(directory) / job_id
            folder.mkdir()
            def fake_import(url, target):
                target.write_bytes(b"sample")
            def fake_render(source, target, start, length, vertical, subtitles):
                target.write_bytes(b"rendered")
            segments = [{"start": 0.0, "end": 29.0, "text": "नमस्ते"}]
            with patch.object(main, "ROOT", Path(directory)), \
                 patch.object(main, "import_youtube_video", side_effect=fake_import), \
                 patch.object(main, "probe", return_value=30.0), \
                 patch.object(main, "transcribe", return_value=segments), \
                 patch.object(main, "render", side_effect=fake_render), \
                 patch.dict(main.jobs, {job_id: {"id": job_id, "status": "queued", "outputs": []}}):
                main.process_link(job_id, "https://youtu.be/abc123def45", (30,))
                job = main.jobs[job_id]
                self.assertEqual(job["status"], "complete", job.get("error"))
                self.assertEqual(len(job["outputs"]), 2)
                self.assertFalse((folder / "source.mp4").exists(), "Imported source should be deleted after rendering")
                for output in job["outputs"]:
                    self.assertTrue((folder / output["name"]).is_file())
                    self.assertTrue((folder / Path(output["srt"]).name).is_file())

    def test_silent_source_fails_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            job_id = "silenttest"
            folder = Path(directory) / job_id
            folder.mkdir()
            source = folder / "source.mp4"
            source.write_bytes(b"fake")
            with patch.object(main, "ROOT", Path(directory)), \\
                 patch.object(main, "probe", return_value=60.0), \\
                 patch.object(main, "transcribe", return_value=[]), \\
                 patch.dict(main.jobs, {job_id: {"id": job_id, "status": "queued", "outputs": []}}):
                main.process(job_id, source, (30,))
                self.assertEqual(main.jobs[job_id]["status"], "failed")
                self.assertFalse(folder.exists())

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_readiness_reports_missing_ffmpeg(self):
        with patch.object(main.shutil, "which", return_value=None):
            response = self.client.get("/api/ready")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["detail"]["dependencies"]["ffmpeg"])

    def test_readiness_requires_auth_when_configured(self):
        with patch.object(main, "API_TOKEN", "secret"):
            response = self.client.get("/api/ready")
            self.assertEqual(response.status_code, 401)

    def test_reject_unsupported_upload(self):
        response = self.client.post("/api/jobs", files={"file": ("bad.txt", io.BytesIO(b"bad"), "text/plain")})
        self.assertEqual(response.status_code, 415)

    def test_reject_invalid_durations(self):
        response = self.client.post("/api/jobs", data={"lengths": "5,999"}, files={"file": ("test.mp4", io.BytesIO(b"fake"), "video/mp4")})
        self.assertEqual(response.status_code, 422)

    def test_token_guard(self):
        with patch.object(main, "API_TOKEN", "unit-test-secret"):
            response = self.client.get("/api/jobs/missing")
            self.assertEqual(response.status_code, 401)
            response = self.client.get("/api/jobs/missing", headers={"Authorization": "Bearer unit-test-secret"})
            self.assertEqual(response.status_code, 404)


    def test_download_rejects_unregistered_files(self):
        with patch.dict(main.jobs, {"testjob": {"status": "complete", "outputs": []}}):
            response = self.client.get("/api/jobs/testjob/files/secret.mp4")
            self.assertEqual(response.status_code, 404)

    def test_download_rejects_incomplete_job(self):
        with patch.dict(main.jobs, {"testjob": {"status": "rendering", "outputs": []}}):
            response = self.client.get("/api/jobs/testjob/files/30s_1_vertical.mp4")
            self.assertEqual(response.status_code, 404)

    def test_rejects_job_when_capacity_reached(self):
        with patch.dict(main.jobs, {"busy": {"status": "rendering", "outputs": []}}):
            with patch.object(main, "MAX_ACTIVE_JOBS", 1):
                response = self.client.post("/api/jobs", files={"file": ("test.mp4", io.BytesIO(b"fake"), "video/mp4")})
                self.assertEqual(response.status_code, 429)

if __name__ == "__main__":
    unittest.main()
