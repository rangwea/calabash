import unittest

from scripts.generate_app_icons import BACKGROUND, TRANSPARENT, WHITE, _render


class AppIconTests(unittest.TestCase):
    def test_c_has_open_right_side_and_retains_transparent_margin(self):
        size = 128
        pixels = _render(size)

        def at_design(x, y):
            px = int(((x - 20) * 0.84 + 20) * size / 40)
            py = int(((y - 20) * 0.84 + 20) * size / 40)
            return pixels[py * size + px]

        self.assertEqual(WHITE, at_design(11.2, 20))
        self.assertEqual(WHITE, at_design(20.7, 10.5))
        self.assertEqual(WHITE, at_design(20.7, 29.5))
        self.assertEqual(BACKGROUND, at_design(20.7, 20))
        self.assertEqual(BACKGROUND, at_design(30.2, 20))
        self.assertEqual(TRANSPARENT, pixels[0])
        self.assertTrue(any(0 < pixel[3] < 255 for pixel in pixels))
