from game_analyzer.timer import TimerReading, parse_timer_from_cdp_value, parse_timer_from_text


def test_parse_header_timer_line():
    text = "Round\n25\nGame ID:105236335\nSpades"
    assert parse_timer_from_text(text) == TimerReading(seconds=25, source="header")


def test_header_preferred_over_footer():
    text = "Round\n24\nGame ID:105249953\n1st 32 to go"
    assert parse_timer_from_text(text) == TimerReading(seconds=24, source="header")


def test_footer_only_when_no_header():
    # Footer is still parseable from text helpers, but CDP no longer returns it for waits.
    text = "Spades\nHearts\n1st 32 to go\nGame ID: 105236335"
    assert parse_timer_from_text(text) == TimerReading(seconds=32, source="footer")


def test_parse_zero_timer():
    text = "Round\n0\nROUND OVER !"
    assert parse_timer_from_text(text) == TimerReading(seconds=0, source="header")


def test_parse_cdp_payload():
    assert parse_timer_from_cdp_value({"seconds": 9, "source": "header"}) == TimerReading(
        seconds=9, source="header"
    )
    assert parse_timer_from_cdp_value({"seconds": 99, "source": "header"}) is None
