import unittest
from app.main import import_error_message


class ImportErrorMessageTests(unittest.TestCase):
    def test_youtube_bot_block(self):
        message = import_error_message(Exception("[youtube] Sign in to confirm you’re not a bot."))
        self.assertIn("blocked automated access", message)
        self.assertIn("MP4/MOV", message)
        self.assertNotIn("cookies for authentication", message)

    def test_unavailable_video(self):
        self.assertIn("unavailable", import_error_message(Exception("Video unavailable")))

    def test_unexpected_exception_does_not_leak_details(self):
        message = import_error_message(Exception("SECRET=private-key"))
        self.assertNotIn("private-key", message)
        self.assertIn("Video import failed", message)


if __name__ == "__main__":
    unittest.main()
