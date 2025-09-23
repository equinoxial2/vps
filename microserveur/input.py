from command_parser import CommandParsingError, parse_trade_command
from main import attendre_commande


def main() -> None:
    """Lit une commande depuis l'entrée standard et affiche l'analyse."""
    try:
        command = attendre_commande()
        parsed = parse_trade_command(command)
        print(parsed)
    except CommandParsingError as exc:
        print(f"Erreur: {exc}")


if __name__ == "__main__":
    main()
