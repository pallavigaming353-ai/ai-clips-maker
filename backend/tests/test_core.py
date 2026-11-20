import unittest
from app.main import srt_time, windows

class CoreTests(unittest.TestCase):
    def test_srt_format(self):
        self.assertEqual(srt_time(3661.234), "01:01:01,234")
        self.assertEqual(srt_time(-2), "00:00:00,000")

    def test_short_source(self):
        self.assertEqual(windows([], 20, 30), [])

    def test_windows_do_not_overlap(self):
        speech = [{"start": i, "end": i + 8, "text": "speech"} for i in range(0, 200, 10)]
        result = windows(speech, 200, 30, limit=3)
        self.assertLessEqual(len(result), 3)
        self.assertTrue(all(0 <= start <= 170 for start in result))
        self.assertTrue(all(abs(a-b) >= 30 for i,a in enumerate(result) for b in result[i+1:]))

    def test_long_window(self):
        self.assertEqual(windows([], 1800, 1800), [0])

if __name__ == "__main__":
    unittest.main()
