"""Model access: three hosted endpoints and one local model behind one interface."""

import json
import os
import re
import time

import requests

CHAT_COMPLETIONS = "/chat/completions"
TIMEOUT = 180

REGISTRY = {
    "gpt-4o": {
        "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o"),
        "direct": ("https://api.openai.com/v1", "gpt-4o"),
        "direct_key": "OPENAI_API_KEY",
    },
    "kimi-k2": {
        "openrouter": ("https://openrouter.ai/api/v1", "moonshotai/kimi-k2"),
        "direct": ("https://api.moonshot.ai/v1", "kimi-k2-0711-preview"),
        "direct_key": "MOONSHOT_API_KEY",
    },
    "deepseek": {
        "openrouter": ("https://openrouter.ai/api/v1", "deepseek/deepseek-chat"),
        "direct": ("https://api.deepseek.com/v1", "deepseek-chat"),
        "direct_key": "DEEPSEEK_API_KEY",
    },
}

LOCAL_MODEL = "Qwen/Qwen2.5-7B-Instruct"


def get_key(name):
    """Read a credential from Colab Secrets, falling back to the environment."""
    try:
        from google.colab import userdata
        value = userdata.get(name)
        if value:
            return value
    except Exception:
        pass
    return os.environ.get(name)


class ApiModel:
    """An OpenAI-compatible chat endpoint, called over plain HTTP."""

    def __init__(self, name, prefer="openrouter", temperature=0.0, max_tokens=4096):
        entry = REGISTRY[name]
        self.name = name
        self.temperature = temperature
        self.max_tokens = max_tokens

        key = get_key("OPENROUTER_API_KEY") if prefer == "openrouter" else None
        if key:
            self.base_url, self.model_id, self.via = (*entry["openrouter"], "openrouter")
        else:
            key = get_key(entry["direct_key"])
            self.base_url, self.model_id, self.via = (*entry["direct"], "direct")
        if not key:
            raise RuntimeError(
                f"No credential for {name}. Add OPENROUTER_API_KEY or "
                f"{entry['direct_key']} to Colab Secrets or the environment.")

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/nxull9/invoice-audit",
            "X-Title": "invoice-audit",
        })

    def generate(self, system, user):
        started = time.time()
        response = self.session.post(
            self.base_url + CHAT_COMPLETIONS,
            json={"model": self.model_id,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}],
                  "temperature": self.temperature,
                  "max_tokens": self.max_tokens},
            timeout=TIMEOUT)
        if response.status_code != 200:
            raise RuntimeError(f"{self.name} returned {response.status_code}: "
                               f"{response.text[:300]}")
        payload = response.json()
        usage = payload.get("usage") or {}
        return payload["choices"][0]["message"]["content"], {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "seconds": round(time.time() - started, 2),
        }


class LocalModel:
    """Qwen2.5-7B-Instruct quantised to 4 bit. No data leaves the machine."""

    def __init__(self, model_id=LOCAL_MODEL, max_tokens=4096):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

        self.name = model_id.split("/")[-1]
        self.model_id = model_id
        self.via = "local"
        self.max_tokens = max_tokens

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True),
            device_map="auto",
            torch_dtype=torch.float16)
        self.model.eval()

    def generate(self, system, user):
        import torch
        started = time.time()
        prompt = self.tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            output = self.model.generate(
                **inputs, max_new_tokens=self.max_tokens, do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id)
        generated = output[0][inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(generated, skip_special_tokens=True), {
            "input_tokens": int(inputs["input_ids"].shape[1]),
            "output_tokens": int(generated.shape[0]),
            "seconds": round(time.time() - started, 2),
        }


class ReplayModel:
    """Replays recorded responses so a committed run reproduces without a key."""

    def __init__(self, responses, name="replay"):
        self.responses = responses
        self.name = name
        self.via = "replay"
        self.calls = 0

    def generate(self, system, user):
        reply = self.responses.get(str(self.calls), '{"services": []}')
        self.calls += 1
        return reply, {"input_tokens": 0, "output_tokens": 0, "seconds": 0.0}


def parse_json(text):
    """Extract a JSON object from a model reply. Returns (object, error)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1]), None
        except json.JSONDecodeError as exc:
            return None, f"unparseable JSON: {exc}"
    return None, "no JSON object in reply"
