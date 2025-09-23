"""Parsing helpers to convert text commands into Binance orders."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional


@dataclass
class ParsedOrder:
    side: str
    symbol: str
    order_type: str
    quantity: str
    price: Optional[str] = None
    time_in_force: Optional[str] = None
    quote_asset: Optional[str] = None
    quote: Optional[str] = None
    callback: Optional[str] = None
    activation_price: Optional[str] = None

    def dict(self) -> dict[str, Optional[str]]:
        return asdict(self)

    def model_dump(self) -> dict[str, Optional[str]]:
        return self.dict()


class CommandParsingError(Exception):
    """Raised when a free-form command cannot be understood."""


RAW_SIDE_KEYWORDS = {
    "buy": "BUY",
    "sell": "SELL",
    "acheter": "BUY",
    "achete": "BUY",
    "achète": "BUY",
    "achetez": "BUY",
    "achetons": "BUY",
    "vendre": "SELL",
    "vend": "SELL",
    "vends": "SELL",
    "vendez": "SELL",
}

RAW_ORDER_TYPE_KEYWORDS = {
    "market": "MARKET",
    "marche": "MARKET",
    "marché": "MARKET",
    "limit": "LIMIT",
    "limite": "LIMIT",
}


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_keyword(token: str) -> str:
    stripped = strip_accents(token).lower()
    return re.sub(r"[^a-z0-9]", "", stripped)


SIDE_KEYWORDS = {normalize_keyword(key): value for key, value in RAW_SIDE_KEYWORDS.items()}
ORDER_TYPE_KEYWORDS = {
    normalize_keyword(key): value for key, value in RAW_ORDER_TYPE_KEYWORDS.items()
}

RAW_CALLBACK_RATE_KEYWORDS = {
    "callback",
    "callback_rate",
    "callbackrate",
    "callback%",
    "taux_callback",
    "taux_de_callback",
    "callback_pourcentage",
}

CALLBACK_RATE_KEYWORDS = {normalize_keyword(key) for key in RAW_CALLBACK_RATE_KEYWORDS}

RAW_ACTIVATION_PRICE_KEYWORDS = {
    "activation",
    "activation_price",
    "activationprice",
    "prix_activation",
    "prix_dactivation",
    "activation_prix",
    "trigger",
    "trigger_price",
    "triggerprice",
    "prix_declenchement",
    "prixdeclenchement",
    "declenchement",
}

ACTIVATION_PRICE_KEYWORDS = {
    normalize_keyword(key) for key in RAW_ACTIVATION_PRICE_KEYWORDS
}

ORDER_KEYWORDS = (
    set(SIDE_KEYWORDS.keys())
    | set(ORDER_TYPE_KEYWORDS.keys())
    | CALLBACK_RATE_KEYWORDS
    | ACTIVATION_PRICE_KEYWORDS
)

KNOWN_SYMBOL_SUFFIXES = {
    "USDT",
    "USDC",
    "BUSD",
    "TUSD",
    "FDUSD",
    "DAI",
    "BTC",
    "ETH",
    "BNB",
    "BIDR",
    "EUR",
    "GBP",
    "TRY",
    "BRL",
    "AUD",
    "PAXG",
}


def is_valid_candidate(candidate: str) -> bool:
    return (
        len(candidate) >= 5
        and candidate.isalnum()
        and any(candidate.endswith(suffix) for suffix in KNOWN_SYMBOL_SUFFIXES)
    )


def detect_quote_asset(symbol: str) -> Optional[str]:
    for suffix in sorted(KNOWN_SYMBOL_SUFFIXES, key=len, reverse=True):
        if symbol.endswith(suffix):
            return suffix
    return None


def decimal_to_str(value: Decimal) -> str:
    quantized = value.normalize()
    as_str = format(quantized, "f")
    if "." in as_str:
        as_str = as_str.rstrip("0").rstrip(".")
    return as_str or "0"


NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])[+-]?\d+(?:[.,]\d+)?(?![A-Za-z0-9])")


def extract_numbers(tokens: list[str]) -> list[Decimal]:
    return [value for _, value in extract_numbers_with_indices(tokens)]


def extract_numbers_with_indices(tokens: list[str]) -> list[tuple[int, Decimal]]:
    numbers: list[tuple[int, Decimal]] = []
    for index, token in enumerate(tokens):
        for match in NUMBER_PATTERN.finditer(token):
            normalized = match.group().replace(",", ".")
            try:
                numbers.append((index, Decimal(normalized)))
            except InvalidOperation:
                continue
    return numbers


def clean_symbol_token(token: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", strip_accents(token))


def extract_symbol(raw_tokens: list[str], keyword_tokens: list[str]) -> Optional[str]:
    cleaned_tokens = [clean_symbol_token(token) for token in raw_tokens]
    for cleaned, keyword_token in zip(cleaned_tokens, keyword_tokens):
        if not cleaned:
            continue
        if keyword_token in ORDER_KEYWORDS:
            continue
        if not any(char.isalpha() for char in cleaned):
            continue
        candidate = cleaned.upper()
        if is_valid_candidate(candidate):
            return candidate
    for idx in range(len(cleaned_tokens) - 1):
        first = cleaned_tokens[idx]
        second = cleaned_tokens[idx + 1]
        first_keyword = keyword_tokens[idx]
        second_keyword = keyword_tokens[idx + 1]
        if (
            not first
            or not second
            or first_keyword in ORDER_KEYWORDS
            or second_keyword in ORDER_KEYWORDS
        ):
            continue
        if not any(char.isalpha() for char in first) or not any(char.isalpha() for char in second):
            continue
        candidate = f"{first}{second}".upper()
        if is_valid_candidate(candidate):
            return candidate
    return None


def parse_trade_command(command: str) -> ParsedOrder:
    raw_tokens = command.strip().split()
    keyword_tokens = [normalize_keyword(token) for token in raw_tokens]

    side = next((SIDE_KEYWORDS[token] for token in keyword_tokens if token in SIDE_KEYWORDS), None)
    if not side:
        raise CommandParsingError("Impossible de déterminer si l'ordre est un achat ou une vente.")

    order_type = next(
        (ORDER_TYPE_KEYWORDS[token] for token in keyword_tokens if token in ORDER_TYPE_KEYWORDS),
        "MARKET",
    )

    symbol = extract_symbol(raw_tokens, keyword_tokens)
    if not symbol:
        raise CommandParsingError("Impossible de déterminer le symbole à trader.")

    numbers_with_indices = extract_numbers_with_indices(raw_tokens)
    if not numbers_with_indices:
        raise CommandParsingError("Impossible de déterminer la quantité à trader.")

    quantity_index, quantity = numbers_with_indices[0]
    if quantity <= 0:
        raise CommandParsingError("La quantité doit être supérieure à zéro.")

    used_number_indices = {quantity_index}

    price: Optional[Decimal] = None
    price_index: Optional[int] = None
    if order_type == "LIMIT":
        if len(numbers_with_indices) < 2:
            raise CommandParsingError("Une commande limite nécessite un prix.")
        price_index, price = numbers_with_indices[1]
        if price <= 0:
            raise CommandParsingError("Le prix doit être supérieur à zéro.")
        used_number_indices.add(price_index)

    def find_number_after_keywords(keywords: set[str]) -> Optional[Decimal]:
        for idx, keyword in enumerate(keyword_tokens):
            if keyword not in keywords:
                continue
            for token_index, value in numbers_with_indices:
                if token_index in used_number_indices:
                    continue
                if token_index >= idx:
                    used_number_indices.add(token_index)
                    return value
        return None

    callback_value = find_number_after_keywords(CALLBACK_RATE_KEYWORDS)
    if callback_value is not None and callback_value <= 0:
        raise CommandParsingError("Le callback doit être supérieur à zéro.")

    activation_value = find_number_after_keywords(ACTIVATION_PRICE_KEYWORDS)
    if activation_value is not None and activation_value <= 0:
        raise CommandParsingError("Le prix d'activation doit être supérieur à zéro.")

    callback_str = decimal_to_str(callback_value) if callback_value is not None else None
    activation_str = (
        decimal_to_str(activation_value) if activation_value is not None else None
    )

    quote_asset = detect_quote_asset(symbol)

    return ParsedOrder(
        side=side,
        symbol=symbol,
        order_type=order_type,
        quantity=decimal_to_str(quantity),
        price=decimal_to_str(price) if price is not None else None,
        time_in_force="GTC" if order_type == "LIMIT" else None,
        quote_asset=quote_asset,
        quote=quote_asset,
        callback=callback_str,
        activation_price=activation_str,
    )


__all__ = [
    "CommandParsingError",
    "ParsedOrder",
    "parse_trade_command",
]
