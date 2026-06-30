from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable


@dataclass
class OpenAICompatClient:
    api_key: str
    model: str
    base_url: str = ""
    timeout: float = 60.0

    def _endpoint(self) -> str:
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        return f"{base}/chat/completions"

    def effective_timeout(self) -> float:
        raw = os.environ.get("AINOVEL_HTTP_TIMEOUT", "").strip()
        if raw:
            try:
                return float(raw)
            except Exception:
                pass
        return self.timeout

    def effective_stream_total_timeout(self) -> float:
        raw = os.environ.get("AINOVEL_STREAM_TOTAL_TIMEOUT", "").strip()
        if raw:
            try:
                value = float(raw)
                if value > 0:
                    return value
            except Exception:
                pass
        return 300.0

    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        req = urllib.request.Request(
            url=self._endpoint(),
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        body = self._perform_request(req)

        try:
            data = json.loads(body)
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
        except Exception as exc:
            raise RuntimeError(f"llm decode failed: {exc}") from exc

    def complete_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        on_delta=None,
        on_chunk: Callable[[str, str], None] | None = None,
        temperature: float = 0.7,
    ) -> str:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        req = urllib.request.Request(
            url=self._endpoint(),
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        total_timeout = self.effective_stream_total_timeout()
        last_error: Exception | None = None
        for attempt in range(2):
            chunks: list[str] = []
            started_at = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.effective_timeout()) as resp:
                    for raw_line in resp:
                        if time.monotonic() - started_at > total_timeout:
                            raise TimeoutError(f"stream total timeout after {total_timeout:.0f}s")
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_line = line[5:].strip()
                        if data_line == "[DONE]":
                            return "".join(chunks).strip()
                        try:
                            data = json.loads(data_line)
                            delta_obj = data.get("choices", [{}])[0].get("delta", {})
                            if not isinstance(delta_obj, dict):
                                continue

                            content_delta = self._extract_stream_text(delta_obj.get("content"))
                            thinking_delta = "".join(
                                [
                                    self._extract_stream_text(delta_obj.get("reasoning")),
                                    self._extract_stream_text(delta_obj.get("reasoning_content")),
                                    self._extract_stream_text(delta_obj.get("thinking")),
                                ]
                            )

                            if thinking_delta and on_chunk:
                                on_chunk("thinking", thinking_delta)
                            if content_delta:
                                chunks.append(content_delta)
                                if on_delta:
                                    on_delta(content_delta)
                                if on_chunk:
                                    on_chunk("content", content_delta)
                        except Exception:
                            continue
                return "".join(chunks).strip()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"llm stream http error {exc.code}: {detail}") from exc
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                raise RuntimeError(f"llm stream request failed: {exc}") from exc
        if last_error:
            raise RuntimeError(f"llm stream request failed: {last_error}")
        return ""

    @staticmethod
    def _extract_stream_text(value: object) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                if isinstance(item, str):
                    out.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        out.append(text)
            return "".join(out)
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str):
                return text
        return ""

    def _perform_request(self, req: urllib.request.Request) -> str:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.effective_timeout()) as resp:
                    return resp.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"llm http error {exc.code}: {detail}") from exc
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                raise RuntimeError(f"llm request failed: {exc}") from exc
        if last_error:
            raise RuntimeError(f"llm request failed: {last_error}")
        raise RuntimeError("llm request failed: unknown error")
