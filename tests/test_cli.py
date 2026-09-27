import pytest

from supernote_todo.cli import parse_account


@pytest.mark.parametrize("text,expected", [
    ("ad@ornek.com", ("ad@ornek.com", None)),
    ("5321234567", ("5321234567", 90)),
    ("0532 123 45 67", ("5321234567", 90)),
    ("+90 532 123 45 67", ("5321234567", 90)),
    ("(532) 123-4567", ("5321234567", 90)),
])
def test_parse_account(text, expected):
    assert parse_account(text) == expected


def test_parse_account_other_country():
    assert parse_account("+1 415 555 0100", "1") == ("4155550100", 1)


def test_parse_account_rejects_garbage():
    with pytest.raises(ValueError):
        parse_account("abc")
