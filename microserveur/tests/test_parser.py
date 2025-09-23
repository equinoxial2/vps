from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from command_parser import CommandParsingError, ParsedOrder, parse_trade_command


@pytest.mark.parametrize(
    "command,expected",
    [
        (
            "Achète 0,1 BTCUSDT au marché",
            ParsedOrder(
                side="BUY",
                symbol="BTCUSDT",
                order_type="MARKET",
                quantity="0.1",
                quote_asset="USDT",
                quote="USDT",
            ),
        ),
        (
            "Vend 2 eth usdt limit à 2300",
            ParsedOrder(
                side="SELL",
                symbol="ETHUSDT",
                order_type="LIMIT",
                quantity="2",
                price="2300",
                time_in_force="GTC",
                quote_asset="USDT",
                quote="USDT",
            ),
        ),
        (
            "achetez 5 sol usdt",
            ParsedOrder(
                side="BUY",
                symbol="SOLUSDT",
                order_type="MARKET",
                quantity="5",
                quote_asset="USDT",
                quote="USDT",
            ),
        ),
        (
            "achète 1 op usdt",
            ParsedOrder(
                side="BUY",
                symbol="OPUSDT",
                order_type="MARKET",
                quantity="1",
                quote_asset="USDT",
                quote="USDT",
            ),
        ),
        (
            "vend 2 santos usdt",
            ParsedOrder(
                side="SELL",
                symbol="SANTOSUSDT",
                order_type="MARKET",
                quantity="2",
                quote_asset="USDT",
                quote="USDT",
            ),
        ),
    ],
)
def test_parse_trade_command_success(command: str, expected: ParsedOrder) -> None:
    parsed = parse_trade_command(command)
    assert parsed.model_dump() == expected.model_dump()


def test_parse_trade_command_detects_quote_with_separator() -> None:
    parsed = parse_trade_command("acheter 1 btc/usdt")
    assert parsed.symbol == "BTCUSDT"
    assert parsed.quote_asset == "USDT"
    assert parsed.quote == "USDT"


def test_parse_trade_command_requires_symbol() -> None:
    with pytest.raises(CommandParsingError):
        parse_trade_command("achète 1 au marché")


def test_parse_trade_command_rejects_negative_quantity() -> None:
    with pytest.raises(CommandParsingError):
        parse_trade_command("acheter -1 btcusdt")


def test_parse_trade_command_limit_requires_price() -> None:
    with pytest.raises(CommandParsingError):
        parse_trade_command("vendre 2 eth usdt limit")


def test_parse_trade_command_extracts_callback_and_activation() -> None:
    parsed = parse_trade_command("vend 3 btcusdt callback 1.5 activation 25000")
    assert parsed.callback == "1.5"
    assert parsed.activation_price == "25000"


def test_parse_trade_command_rejects_negative_callback() -> None:
    with pytest.raises(CommandParsingError):
        parse_trade_command("acheter 1 btcusdt callback -1")


def test_parse_trade_command_rejects_negative_activation_price() -> None:
    with pytest.raises(CommandParsingError):
        parse_trade_command("acheter 1 btcusdt activation -100")
