import io
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import main

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_youtube_url_validation(self):
        self.assertTrue(main.is_youtube_url("https://www.youtube.com/watch?v=abc123"))
        self.assertTrue(main.is_youtube_url("https://youtu.be/abc123"))
        self.assertFalse(main.is_youtube_url("http://youtube.com/watch?v=abc123"))
        self.assertFalse(main.is_youtube_url("https://youtube.com.evil.example/watch?v=abc123"))
        self.assertFalse(main.is_youtube_url("https://youtube.com:444/watch?v=abc123"))

    def test_youtube_link_job_invalid_duration(self):
        response = self.client.post("/api/jobs/from-link", data={"url": "https://youtu.be/abc123", "lengths": "999"})
        self.assertEqual(response.status_code, 422)

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

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
