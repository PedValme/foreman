import unittest

from cart import total


class CartTest(unittest.TestCase):
    def test_total(self):
        self.assertEqual(total([10, 20, 30]), 60)

    def test_discount_is_a_percentage(self):
        self.assertEqual(total([100], discount=10), 90)


if __name__ == "__main__":
    unittest.main()
