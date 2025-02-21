"""Dummy test cases to initialize the repository."""

from secrets import randbelow

from old_country.dummy import dummy


def test_dummy() -> None:
    """Dummy test case."""
    x = randbelow(10)
    assert dummy(x) == x
