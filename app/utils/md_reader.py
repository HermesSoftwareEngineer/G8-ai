import os
import logging

logger = logging.getLogger(__name__)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SHOP_INFO_PATH = os.path.join(_ROOT, "shop_info.md")
PROMPT_PATH    = os.path.join(_ROOT, "prompt.md")


def _read(path: str, fallback: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("%s não encontrado", path)
        return fallback


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def read_shop_info() -> str:
    return _read(SHOP_INFO_PATH, "Informações da barbearia não disponíveis no momento.")


def write_shop_info(content: str) -> None:
    _write(SHOP_INFO_PATH, content)


def read_prompt() -> str:
    return _read(PROMPT_PATH, "Você é a G8 AI, atendente da Barbershop G8.")


def write_prompt(content: str) -> None:
    _write(PROMPT_PATH, content)
