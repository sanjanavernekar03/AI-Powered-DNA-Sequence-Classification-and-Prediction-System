import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional

from flask import current_app

logger = logging.getLogger(__name__)

class ChatbotServiceError(RuntimeError):
    """Raised when the local chatbot service cannot answer a request."""


def _build_ollama_messages(
    message: str,
    language: str,
    conversation: List[Dict[str, str]] | None = None,
) -> List[Dict[str, str]]:
    lang_map = {'en': 'English', 'hi': 'Hindi', 'kn': 'Kannada', 'te': 'Telugu', 'ta': 'Tamil'}
    full_lang = lang_map.get(language, 'English')
    
    system_prompt = (
        "You are DNAura Health & DNA Assistant. Answer questions clearly, accurately, "
        "and concisely. Help users understand DNA, mutations, health, diet, and wellness. "
        "Keep answers crisp and direct unless the user asks for deep detail. "
        "Never provide a clinical medical diagnosis; recommend a qualified professional when appropriate. "
        f"CRITICAL REQUIREMENT: The user has selected the language: {full_lang}. "
        f"You MUST write your entire response strictly in {full_lang} (using {full_lang} script). "
        f"Do not respond in English when {full_lang} is selected."
    )
    messages = [{"role": "system", "content": system_prompt}]
    if conversation:
        # Keep only the last 4 turns to avoid token bloat
        for item in conversation[-4:]:
            if (
                item.get("role") in {"user", "assistant"}
                and isinstance(item.get("content"), str)
                and item["content"].strip()
            ):
                messages.append({"role": item["role"], "content": item["content"].strip()})
    messages.append({"role": "user", "content": message.strip()})
    return messages


def stream_chatbot_tokens(
    user_message: str,
    language: str = "en",
    conversation: List[Dict[str, str]] | None = None,
) -> Generator[str, None, None]:
    """
    Stream tokens in real-time from the local Ollama LLM.
    Allows frontend to render progressively with sub-second time-to-first-token.
    """
    message = user_message.strip()
    if not message:
        raise ChatbotServiceError("Message cannot be empty.")

    model = current_app.config.get("OLLAMA_MODEL", "llama3.2")
    base_url = current_app.config.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    messages = _build_ollama_messages(message, language, conversation)

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": "24h",
        "options": {
            "num_predict": 250,
            "temperature": 0.3,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            for line in response:
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode("utf-8"))
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and not model.endswith(":latest"):
            # Try fallback to model:latest
            fallback_payload = json.dumps({
                "model": f"{model}:latest",
                "messages": messages,
                "stream": True,
                "keep_alive": "24h",
                "options": {
                    "num_predict": 250,
                    "temperature": 0.3,
                },
            }).encode("utf-8")
            fallback_req = urllib.request.Request(
                f"{base_url}/api/chat",
                data=fallback_payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(fallback_req, timeout=90) as fallback_resp:
                    for line in fallback_resp:
                        if not line:
                            continue
                        chunk = json.loads(line.decode("utf-8"))
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                return
            except Exception:
                pass
        raise ChatbotServiceError(f"Model error or '{model}' not found in Ollama.") from exc
    except Exception as exc:
        logger.warning("Error streaming chatbot tokens: %s", exc)
        raise ChatbotServiceError(f"Streaming error: {exc}") from exc


def get_chatbot_response(
    user_message: str,
    current_page: str = "",
    language: str = "en",
    conversation: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """Generate a complete response from the local Ollama model."""
    message = user_message.strip()
    if not message:
        raise ChatbotServiceError("Message cannot be empty.")

    model = current_app.config.get("OLLAMA_MODEL", "llama3.2")
    base_url = current_app.config.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    try:
        response_text = _call_ollama(
            message,
            language,
            conversation or [],
            model,
            base_url,
        )
    except TimeoutError as exc:
        logger.warning("Ollama connection timed out: %s", exc)
        raise ChatbotServiceError("The AI model is warming up or taking longer to process. Please try sending your message again.") from exc
    except urllib.error.HTTPError as exc:
        logger.warning("Ollama returned HTTP status %s", exc.code)
        if exc.code == 404:
            if not model.endswith(":latest"):
                try:
                    response_text = _call_ollama(
                        message,
                        language,
                        conversation or [],
                        f"{model}:latest",
                        base_url,
                    )
                    return {"response": response_text, "language": language}
                except Exception:
                    pass
            raise ChatbotServiceError(f"The selected model '{model}' is not installed in Ollama. Pull it using 'ollama pull {model}'.") from exc
        raise ChatbotServiceError("The local chatbot service returned an error.") from exc
    except urllib.error.URLError as exc:
        logger.warning("Ollama connection failed: %s", exc)
        raise ChatbotServiceError("Ollama service is not reachable on http://127.0.0.1:11434. Please ensure Ollama is running.") from exc
    except json.JSONDecodeError as exc:
        logger.warning("Ollama returned invalid JSON")
        raise ChatbotServiceError("The local chatbot returned an invalid response.") from exc

    return {
        "response": response_text,
        "language": language,
        "intent": "CHATBOT_QUERY",
    }


def _call_ollama(
    message: str,
    language: str,
    conversation: List[Dict[str, str]],
    model: str,
    base_url: str,
) -> str:
    messages = _build_ollama_messages(message, language, conversation)

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": "24h",
        "options": {
            "num_predict": 250,
            "temperature": 0.3,
        },
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.loads(response.read().decode("utf-8"))

    response_text = result.get("message", {}).get("content", "").strip()
    if not response_text:
        raise ChatbotServiceError("The local chatbot returned an empty response.")
    return response_text
