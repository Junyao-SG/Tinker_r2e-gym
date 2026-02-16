"""
Lightweight OpenAI-compatible proxy for Tinker's SamplingClient.

Exposes Tinker model inference as an OpenAI /v1/chat/completions endpoint,
so R2E-Gym's Agent can use it with --llm_name "openai/gpt-tinker" and LLM_BASE_URL.

Supports OpenAI function calling: accepts ``tools`` in the request body,
formats them via Qwen3's chat template, and parses ``<tool_call>`` blocks
from model output back into OpenAI ``tool_calls`` response format.

Usage:
    # Serve base model
    python -m tinker_r2egym.tinker_proxy --model_name "Qwen/Qwen3-30B-A3B"

    # Serve fine-tuned checkpoint
    python -m tinker_r2egym.tinker_proxy --model_name "Qwen/Qwen3-30B-A3B" \
        --weights_path "tinker://run-id/weights/checkpoint-000050"

    # Then run R2E-Gym with:
    LLM_BASE_URL=http://localhost:8080/v1 python src/r2egym/agenthub/run/edit.py runagent_multiple \
        --llm_name "openai/gpt-tinker" --use_fn_calling True --backend docker ...
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import tinker
import tinker.types as types
from transformers import AutoTokenizer

logger = logging.getLogger(__name__)


class TinkerInferenceServer:
    """Wraps Tinker SamplingClient as an OpenAI-compatible API."""

    def __init__(
        self,
        model_name: str,
        weights_path: Optional[str] = None,
        port: int = 8080,
    ):
        self.model_name = model_name
        self.port = port

        logger.info(f"Loading tokenizer: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

        logger.info("Connecting to Tinker API")
        self.service_client = tinker.ServiceClient()

        if weights_path:
            logger.info(f"Loading fine-tuned weights: {weights_path}")
            training_client = self.service_client.create_lora_training_client(
                base_model=model_name
            )
            self.sampling_client = training_client.create_sampling_client(weights_path)
        else:
            logger.info(f"Using base model: {model_name}")
            self.sampling_client = self.service_client.create_sampling_client(
                base_model=model_name
            )

        logger.info("Tinker SamplingClient ready")

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        stop: Optional[list[str]] = None,
        tools: Optional[list[dict]] = None,
    ) -> dict:
        """Generate a chat completion from messages.

        When ``tools`` is provided (forwarded from the request body), they are
        passed to the tokenizer's chat template so Qwen3 sees them in its
        native Hermes format.  The model's ``<tool_call>`` output blocks are
        then parsed back into OpenAI ``tool_calls`` response format.
        """
        # Format messages into a single prompt using the tokenizer's chat template.
        # When tools are present, the tokenizer injects them in Qwen3's native format.
        template_kwargs: dict = dict(
            tokenize=False, add_generation_prompt=True,
        )
        if tools:
            template_kwargs["tools"] = tools
        prompt_text = self.tokenizer.apply_chat_template(
            messages, **template_kwargs,
        )
        prompt_tokens = self.tokenizer.encode(prompt_text)

        # Sample from Tinker
        params = types.SamplingParams(
            max_tokens=max_tokens,
            temperature=max(temperature, 0.01),  # Tinker doesn't accept exactly 0
            stop=stop or [],
        )
        future = self.sampling_client.sample(
            prompt=types.ModelInput.from_ints(prompt_tokens),
            num_samples=1,
            sampling_params=params,
        )
        result = future.result()

        # Decode the response
        output_tokens = list(result.sequences[0].tokens)
        completion_text = self.tokenizer.decode(output_tokens, skip_special_tokens=True)

        # Check for tool calls in the output
        tool_calls = _parse_tool_calls(completion_text) if tools else []

        if tool_calls:
            # Strip the <tool_call> blocks from content, keep any preceding text
            content = re.split(r"<tool_call>", completion_text, maxsplit=1)[0].strip() or None
            message: dict = {"role": "assistant", "content": content, "tool_calls": tool_calls}
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": completion_text}
            finish_reason = "stop"

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_name,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": len(prompt_tokens),
                "completion_tokens": len(output_tokens),
                "total_tokens": len(prompt_tokens) + len(output_tokens),
            },
        }


_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL,
)


def _parse_tool_calls(text: str) -> list[dict]:
    """Extract Qwen3 ``<tool_call>`` blocks and convert to OpenAI format.

    Qwen3 outputs tool calls as::

        <tool_call>
        {"name": "execute_bash", "arguments": {"command": "ls"}}
        </tool_call>

    Returns a list of OpenAI-format tool_call dicts.
    """
    tool_calls = []
    for match in _TOOL_CALL_RE.finditer(text):
        try:
            call = json.loads(match.group(1))
        except json.JSONDecodeError:
            logger.warning("Failed to parse tool_call JSON: %s", match.group(1))
            continue

        arguments = call.get("arguments", {})
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments)

        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {
                "name": call.get("name", ""),
                "arguments": arguments,
            },
        })
    return tool_calls


def create_handler(server: TinkerInferenceServer):
    """Create an HTTP request handler bound to the inference server."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path in ("/v1/chat/completions", "/chat/completions"):
                content_length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(content_length))

                try:
                    result = server.generate(
                        messages=body.get("messages", []),
                        temperature=body.get("temperature", 0.0),
                        max_tokens=body.get("max_tokens", 4096),
                        stop=body.get("stop"),
                        tools=body.get("tools"),
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(result).encode())
                except Exception as e:
                    logger.error(f"Generation error: {e}")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_GET(self):
            if self.path in ("/v1/models", "/models"):
                result = {
                    "data": [{"id": server.model_name, "object": "model"}]
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            elif self.path == "/health":
                self.send_response(200)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            logger.info(format % args)

    return Handler


def main(
    model_name: str = "Qwen/Qwen3-30B-A3B",
    weights_path: str = "",
    port: int = 8080,
):
    """Start the Tinker inference proxy server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    server = TinkerInferenceServer(
        model_name=model_name,
        weights_path=weights_path or None,
        port=port,
    )

    handler = create_handler(server)
    httpd = HTTPServer(("0.0.0.0", port), handler)
    logger.info(f"Tinker proxy listening on http://0.0.0.0:{port}")
    logger.info(f"Use with: LLM_BASE_URL=http://localhost:{port}/v1 --llm_name 'openai/gpt-tinker'")
    httpd.serve_forever()


if __name__ == "__main__":
    import fire
    fire.Fire(main)
