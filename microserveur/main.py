import re
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    api_key: str = Field(..., validation_alias="BINANCE_API_KEY")
    api_secret: str = Field(..., validation_alias="BINANCE_API_SECRET")
    testnet_api_key: Optional[str] = Field(None, validation_alias="BINANCE_TESTNET_API_KEY")
    testnet_api_secret: Optional[str] = Field(None, validation_alias="BINANCE_TESTNET_API_SECRET")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Settings will automatically read from .env or environment variables
    return Settings()


class CommandRequest(BaseModel):
    command: str
    testnet: bool = True

    @field_validator("command")
    def command_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Le texte de commande ne peut pas être vide.")
        return value


class ParsedOrder(BaseModel):
    side: str
    symbol: str
    order_type: str
    quantity: str
    price: Optional[str] = None
    time_in_force: Optional[str] = None


class CommandParsingError(Exception):
    pass


SIDE_KEYWORDS = {
    "buy": "BUY",
    "sell": "SELL",
    "acheter": "BUY",
    "vendre": "SELL",
}

ORDER_TYPE_KEYWORDS = {
    "market": "MARKET",
    "marche": "MARKET",
    "limit": "LIMIT",
    "limite": "LIMIT",
}

ORDER_KEYWORDS = set(SIDE_KEYWORDS.keys()) | set(ORDER_TYPE_KEYWORDS.keys())


def decimal_to_str(value: Decimal) -> str:
    quantized = value.normalize()
    as_str = format(quantized, "f")
    if "." in as_str:
        as_str = as_str.rstrip("0").rstrip(".")
    return as_str or "0"


def extract_numbers(tokens: list[str]) -> list[Decimal]:
    numbers = []
    for token in tokens:
        normalized = token.replace(",", ".")
        try:
            numbers.append(Decimal(normalized))
        except InvalidOperation:
            continue
    return numbers


def extract_symbol(raw_tokens: list[str]) -> Optional[str]:
    cleaned_tokens = [re.sub(r"[^A-Za-z0-9]", "", token) for token in raw_tokens]
    for cleaned in cleaned_tokens:
        candidate = cleaned.upper()
        if not candidate or candidate.lower() in ORDER_KEYWORDS:
            continue
        if len(candidate) >= 5:
            return candidate
    for idx in range(len(cleaned_tokens) - 1):
        first = cleaned_tokens[idx].upper()
        second = cleaned_tokens[idx + 1].upper()
        if first.lower() in ORDER_KEYWORDS or second.lower() in ORDER_KEYWORDS:
            continue
        if 3 <= len(first) <= 4 and 3 <= len(second) <= 4:
            return f"{first}{second}"
    return None


def parse_trade_command(command: str) -> ParsedOrder:
    raw_tokens = command.strip().split()
    lower_tokens = [token.lower() for token in raw_tokens]

    side = next((SIDE_KEYWORDS[token] for token in lower_tokens if token in SIDE_KEYWORDS), None)
    if not side:
        raise CommandParsingError("Impossible de déterminer si l'ordre est un achat ou une vente.")

    order_type = next((ORDER_TYPE_KEYWORDS[token] for token in lower_tokens if token in ORDER_TYPE_KEYWORDS), "MARKET")

    symbol = extract_symbol(raw_tokens)
    if not symbol:
        raise CommandParsingError("Impossible de déterminer le symbole à trader.")

    numbers = extract_numbers(raw_tokens)
    if not numbers:
        raise CommandParsingError("Impossible de déterminer la quantité à trader.")

    quantity = numbers[0]
    if quantity <= 0:
        raise CommandParsingError("La quantité doit être supérieure à zéro.")

    price: Optional[Decimal] = None
    if order_type == "LIMIT":
        if len(numbers) < 2:
            raise CommandParsingError("Une commande limite nécessite un prix.")
        price = numbers[1]
        if price <= 0:
            raise CommandParsingError("Le prix doit être supérieur à zéro.")

    return ParsedOrder(
        side=side,
        symbol=symbol,
        order_type=order_type,
        quantity=decimal_to_str(quantity),
        price=decimal_to_str(price) if price is not None else None,
        time_in_force="GTC" if order_type == "LIMIT" else None,
    )


def create_client(use_testnet: bool) -> Client:
    settings = get_settings()
    if use_testnet:
        key = settings.testnet_api_key or settings.api_key
        secret = settings.testnet_api_secret or settings.api_secret
        return Client(key, secret, testnet=True)
    return Client(settings.api_key, settings.api_secret)


def attendre_commande() -> str:
    """Attend une saisie utilisateur et renvoie le texte saisi."""
    try:
        return input("Commande à exécuter : ").strip()
    except EOFError as exc:  # pragma: no cover - interaction utilisateur
        raise CommandParsingError("Aucune commande saisie.") from exc


app = FastAPI()


@app.get("/")
def read_root():
    return {"status": "ready"}


@app.post("/orders")
def place_order(payload: CommandRequest):
    try:
        parsed = parse_trade_command(payload.command)
    except CommandParsingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    client = create_client(payload.testnet)
    order_payload = {
        "symbol": parsed.symbol,
        "side": parsed.side,
        "type": parsed.order_type,
        "quantity": parsed.quantity,
    }
    if parsed.order_type == "LIMIT":
        if parsed.price is None:
            raise HTTPException(status_code=500, detail="Le prix de l'ordre limite est manquant après l'analyse.")
        order_payload["timeInForce"] = parsed.time_in_force or "GTC"
        order_payload["price"] = parsed.price

    try:
        response = client.create_order(**order_payload)
    except (BinanceAPIException, BinanceRequestException) as exc:
        raise HTTPException(status_code=502, detail=f"Erreur Binance : {exc.message}") from exc
    except Exception as exc:  # pragma: no cover - unexpected errors
        raise HTTPException(status_code=500, detail="Erreur inattendue lors de l'envoi de l'ordre.") from exc
    finally:
        try:
            client.close_connection()
        except Exception:
            pass

    return {"parsed_order": parsed.dict(), "binance_response": response}
