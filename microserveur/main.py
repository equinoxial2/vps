from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from command_parser import CommandParsingError, parse_trade_command


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


def success_response(message: str, data: Optional[dict] = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "success", "message": message, "data": data},
    )


def error_response(status_code: int, message: str, data: Optional[dict] = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": message, "data": data},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return error_response(422, "Requête invalide.", {"errors": exc.errors()})


@app.get("/")
def read_root():
    return success_response("Service prêt.")


@app.post("/orders")
def place_order(payload: CommandRequest):
    try:
        parsed = parse_trade_command(payload.command)
    except CommandParsingError as exc:
        return error_response(400, str(exc))

    client = create_client(payload.testnet)
    order_payload = {
        "symbol": parsed.symbol,
        "side": parsed.side,
        "type": parsed.order_type,
        "quantity": parsed.quantity,
    }
    if parsed.order_type == "LIMIT":
        if parsed.price is None:
            return error_response(
                500, "Le prix de l'ordre limite est manquant après l'analyse."
            )
        order_payload["timeInForce"] = parsed.time_in_force or "GTC"
        order_payload["price"] = parsed.price

    try:
        response = client.create_order(**order_payload)
    except (BinanceAPIException, BinanceRequestException) as exc:
        error_details = {
            "code": getattr(exc, "code", None),
            "message": exc.message,
        }
        return error_response(502, "Erreur renvoyée par Binance.", error_details)
    except Exception as exc:  # pragma: no cover - unexpected errors
        return error_response(500, "Erreur inattendue lors de l'envoi de l'ordre.")
    finally:
        try:
            client.close_connection()
        except Exception:
            pass

    return success_response(
        "Ordre transmis avec succès.",
        {
            "parsed_order": parsed.dict(),
            "binance_response": response,
        },
    )
