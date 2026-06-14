import os
import logging

logger = logging.getLogger(__name__)

SHOP_INFO_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "shop_info.md")


def read_shop_info() -> str:
    try:
        with open(os.path.abspath(SHOP_INFO_PATH), "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("shop_info.md não encontrado")
        return "Informações da barbearia não disponíveis no momento."


def write_shop_info(content: str) -> None:
    with open(os.path.abspath(SHOP_INFO_PATH), "w", encoding="utf-8") as f:
        f.write(content)
