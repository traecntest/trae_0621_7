"""Local multimodal LLM client.

Talks to a locally-deployed vision-language model (LLaVA / BakLLaVA) through
the Ollama HTTP API so that no external cloud API is required.  When the
backend is unreachable the caller falls back to rule-based heuristics, so
the system keeps working on machines without a GPU or model installed.
"""

from __future__ import annotations

import base64
import os
from typing import Optional

import requests

from ..core.config import AppConfig
from ..core.exceptions import LLMUnavailableError
from ..core.logger import get_logger

log = get_logger("analysis.llm")


class LLMClient:
    """Thin wrapper around the Ollama ``/api/generate`` endpoint."""

    def __init__(self, config: AppConfig) -> None:
        self.base_url = config.ollama_base_url.rstrip("/")
        self.model = config.llm_model
        self.timeout = 30

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def analyze(self, prompt: str, image_path: Optional[str] = None) -> str:
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        if image_path and os.path.isfile(image_path):
            with open(image_path, "rb") as fh:
                encoded = base64.b64encode(fh.read()).decode("utf-8")
            payload["images"] = [encoded]

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("response", "")).strip()
        except (requests.RequestException, ValueError) as exc:
            raise LLMUnavailableError(
                f"多模态大模型不可用 ({self.base_url}): {exc}"
            ) from exc
