"""A tiny shopping cart with one bug, for trying Foreman.

`discount` is a percentage (10 means 10 %), but `total` treats it as a fraction, so a 10 % discount
on 100 gives -900 instead of 90. The test `test_discount_is_a_percentage` catches it.
"""


def total(prices, discount=0):
    """The sum of `prices`, less `discount` percent."""
    return sum(prices) - discount * sum(prices)
