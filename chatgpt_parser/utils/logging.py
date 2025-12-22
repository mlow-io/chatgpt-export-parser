import logging
import os
import sys
from typing import Optional

def setup_logging(output_dir: Optional[str], verbose: bool = True) -> logging.Logger:
    logger = logging.getLogger("chatgpt_export_parser")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        for h in logger.handlers:
            try:
                h.close()
            except Exception:
                pass
        logger.handlers.clear()

    # Console handler
    if verbose:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch_formatter = logging.Formatter("%(levelname)s: %(message)s")
        ch.setFormatter(ch_formatter)
        logger.addHandler(ch)

    # File handler (if we have an output dir)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        log_path = os.path.join(output_dir, "parser.log")
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(fh_formatter)
        logger.addHandler(fh)

    return logger


def attach_file_handler(logger: logging.Logger, output_dir: Optional[str]) -> None:
    """Add a file handler for parser.log in the given output_dir if not already present."""
    if not output_dir:
        return
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "parser.log")
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == os.path.abspath(log_path):
            return
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(fh_formatter)
    logger.addHandler(fh)
