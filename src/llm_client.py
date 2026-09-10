"""One interface, four models.

Every model in the comparison is reached through the same `generate(prompt, text)`
call, so the bake-off changes one string and nothing else. Three are OpenAI-compatible
HTTP APIs and differ only in base URL and model id; the fourth runs locally on the
GPU through transformers.

Keys are never written into the notebook or this file. On Colab they come from the
Secrets panel, locally from the environment. A key pasted into a cell would be saved
into the .ipynb and pushed to GitHub, which is how keys leak.

The local model is the point of the exercise rather than a curiosity: it is the only
one that proves the pipeline can run with no data leaving the machine. What that costs
in accuracy is measured rather than assumed.
"""

import json
import os
import re
import time


def get_key(name):
    """Read an API key from Colab Secrets if present, else the environment."""
    try:
        from google.colab import userdata          # noqa: F401
        try:
            value = userdata.get(name)
            if value:
                return value
        except Exception:
            pass
    except ImportError:
        pass
    return os.environ.get(name)


# --------------------------------------------------------------------------
# Model registry
# --------------------------------------------------------------------------
# `via` is which credential to use. OpenRouter reaches all three hosted models with a
# single key, which is why it is the default; the direct routes are kept so the same
# code works if you hold separate accounts.

REGISTRY = {
    "gpt-4o": {
        "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4o"),
        "direct":     ("https://api.openai.com/v1", "gpt-4o"),
        "direct_key": "OPENAI_API_KEY",
        "role": "closed API baseline",
    },
    "kimi-k2": {
        "openrouter": ("https://openrouter.ai/api/v1", "moonshotai/kimi-k2"),
        "direct":     ("https://api.moonshot.ai/v1", "kimi-k2-0711-preview"),
        "direct_key": "MOONSHOT_API_KEY",
        "role": "open weights, hosted",
    },
    "deepseek": {
        "openrouter": ("https://openrouter.ai/api/v1", "deepseek/deepseek-chat"),
        "direct":     ("https://api.deepseek.com/v1", "deepseek-chat"),
        "direct_key": "DEEPSEEK_API_KEY",
        "role": "open weights (MIT), hosted",
    },
}

LOCAL_MODEL = "Qwen/Qwen2.5-7B-Instruct"


class ApiModel:
    """An OpenAI-compatible chat endpoint. Works for all three hosted models."""

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
                f"no key for {name}. Set OPENROUTER_API_KEY, or {entry['direct_key']}, "
                f"in Colab Secrets (key icon, left sidebar) or the environment.")

        from openai import OpenAI
        self.client = OpenAI(api_key=key, base_url=self.base_url)

    def generate(self, system, user):
        """Return (text, usage). Temperature 0 so a rerun gives the same answer."""
        started = time.time()
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        usage = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "seconds": round(time.time() - started, 2),
        }
        return response.choices[0].message.content, usage


class LocalModel:
    """Qwen2.5-7B-Instruct, loaded onto the Colab GPU in 4-bit.

    Nothing leaves the machine. This is the model that demonstrates the pipeline can
    run inside a hospital's own network, and the accuracy cost of that is what the
    comparison measures.
    """

    def __init__(self, model_id=LOCAL_MODEL, max_tokens=4096):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

        self.name = model_id.split("/")[-1]
        self.model_id = model_id
        self.via = "local"
        self.max_tokens = max_tokens

        quant = BitsAndBytesConfig(load_in_4bit=True,
                                   bnb_4bit_compute_dtype=torch.float16,
                                   bnb_4bit_quant_type="nf4",
                                   bnb_4bit_use_double_quant=True)
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id, quantization_config=quant, device_map="auto", torch_dtype=torch.float16)
        self.model.eval()

    def generate(self, system, user):
        import torch
        started = time.time()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        text = self.tokenizer.apply_chat_template(messages, tokenize=False,
                                                  add_generation_prompt=True)
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=self.max_tokens,
                                      do_sample=False,             # greedy: reproducible
                                      pad_token_id=self.tokenizer.eos_token_id)
        generated = out[0][inputs["input_ids"].shape[1]:]
        usage = {
            "input_tokens": int(inputs["input_ids"].shape[1]),
            "output_tokens": int(generated.shape[0]),
            "seconds": round(time.time() - started, 2),
        }
        return self.tokenizer.decode(generated, skip_special_tokens=True), usage


class StubModel:
    """A fake model that replays saved responses.

    Lets the whole pipeline be tested, and the notebook re-run, without a key, a GPU
    or a network call. Also makes the submission reproducible by anyone who clones the
    repository: the recorded responses are committed, so `submission.csv` can be
    rebuilt exactly without paying for inference.
    """

    def __init__(self, responses, name="stub"):
        self.responses = responses
        self.name = name
        self.via = "replay"
        self.calls = 0

    def generate(self, system, user):
        key = str(self.calls)
        self.calls += 1
        payload = self.responses.get(key, '{"services": []}')
        return payload, {"input_tokens": 0, "output_tokens": 0, "seconds": 0.0}


def parse_json(text):
    """Pull a JSON object out of a model's reply.

    Models wrap JSON in prose or markdown fences however firmly you ask them not to,
    and a parse failure must be a recorded outcome rather than a crash: "returned
    unparseable JSON" is itself a result worth reporting in the comparison.
    """
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
    return None, "no JSON object found in reply"
