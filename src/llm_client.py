"""Model access: three hosted endpoints and one local model behind one interface."""

import json
import os
import random
import re
import time

import requests

CHAT_COMPLETIONS = "/chat/completions"
TIMEOUT = 180

# Shared-pool endpoints return 429 when the upstream provider is saturated, and 5xx
# transiently. Both are expected operating conditions rather than failures, so they
# are retried with exponential backoff and jitter. A non-retryable status is raised
# immediately: retrying a malformed request or a bad credential only wastes time.
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
BACKOFF_BASE = 2.0

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

# Schema enforced at the sampler rather than requested in the prompt. Prompting for
# JSON gets validity most of the time; a declared schema gets it every time, and it
# removes the failure that cost the local model 40% of rows on a nested layout.
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "services": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "unit_basis": {"type": "string", "enum": [
                        "per_hour", "per_day", "per_visit", "per_procedure", "per_test",
                        "per_item", "per_night", "per_unit_dispensed", "per_hour_per_item"]},
                    "rate_cents": {"type": "integer"},
                    "rate_cents_after": {"type": ["integer", "null"]},
                    "rate_change_date": {"type": ["string", "null"]},
                    "daily_cap": {"type": ["integer", "null"]},
                    "confidence": {"type": "number"},
                    "source_quote": {"type": "string"},
                },
                "required": ["service", "unit_basis", "rate_cents", "rate_cents_after",
                             "rate_change_date", "daily_cap", "confidence", "source_quote"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["services"],
    "additionalProperties": False,
}

LOCAL_MODEL = "Qwen/Qwen2.5-7B-Instruct"
LOCAL_FALLBACK = "Qwen/Qwen2.5-3B-Instruct"
BITSANDBYTES_MIN = (0, 46, 1)


def bitsandbytes_ready():
    """Whether 4-bit loading is available in the *running* interpreter.

    Version matters, not presence: transformers rejects older releases, and pip cannot
    replace a package already imported, so an upgrade without a session restart leaves
    the old one loaded and the check must catch that.
    """
    try:
        import bitsandbytes
        version = tuple(int(x) for x in bitsandbytes.__version__.split(".")[:3])
        return version >= BITSANDBYTES_MIN, bitsandbytes.__version__
    except Exception as exc:
        return False, str(exc)


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

    def __init__(self, name, prefer="openrouter", temperature=0.0, max_tokens=4096,
                 schema=None):
        entry = REGISTRY[name]
        self.name = name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.schema = schema
        self.schema_enforced = None

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
        body = {"model": self.model_id,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens}
        if self.schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction", "strict": True,
                                "schema": self.schema}}
        started, retries, last = time.time(), 0, None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self.session.post(self.base_url + CHAT_COMPLETIONS,
                                             json=body, timeout=TIMEOUT)
            except requests.RequestException as exc:
                last, retries = f"{type(exc).__name__}: {exc}", retries + 1
                self._wait(attempt)
                continue

            if response.status_code == 200:
                if self.schema_enforced is None:
                    self.schema_enforced = "response_format" in body
                payload = response.json()
                usage = payload.get("usage") or {}
                return payload["choices"][0]["message"]["content"], {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "seconds": round(time.time() - started, 2),
                    "retries": retries,
                    "schema_enforced": bool(self.schema_enforced),
                }

            last = f"{response.status_code}: {response.text[:200]}"

            # Not every provider or model supports a declared schema. Rather than fail,
            # drop it once and continue by prompting, recording that the run was not
            # schema-enforced so the comparison can say which models had the guarantee.
            if (self.schema and "response_format" in body
                    and response.status_code in (400, 404, 422)):
                body.pop("response_format")
                self.schema_enforced = False
                continue

            if response.status_code not in RETRY_STATUS:
                raise RuntimeError(f"{self.name} returned {last}")

            retries += 1
            self._wait(attempt, response.headers.get("Retry-After"))

        raise RuntimeError(f"{self.name} failed after {MAX_ATTEMPTS} attempts. Last: {last}")

    @staticmethod
    def _wait(attempt, retry_after=None):
        """Exponential backoff with jitter, honouring Retry-After when supplied."""
        if retry_after:
            try:
                time.sleep(min(float(retry_after), 60))
                return
            except ValueError:
                pass
        time.sleep(min(BACKOFF_BASE ** attempt + random.uniform(0, 1), 60))


class LocalModel:
    """Qwen2.5-7B-Instruct quantised to 4 bit. No data leaves the machine."""

    def __init__(self, model_id=None, max_tokens=4096, schema=None):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

        quantised, detail = bitsandbytes_ready()
        if model_id is None:
            # Without working 4-bit, a 7B model in fp16 needs ~15 GB and will not fit a
            # T4 alongside activations. The 3B fits in fp16 at ~6 GB, so the local
            # result is still produced and the substitution is reported rather than
            # silently changing what was measured.
            model_id = LOCAL_MODEL if quantised else LOCAL_FALLBACK
            if not quantised:
                print(f"bitsandbytes unusable ({detail}); 4-bit disabled.")
                print(f"Falling back to {model_id} in fp16.")
                print("For the 7B: !pip install -U 'bitsandbytes>=0.46.1' "
                      "then Runtime > Restart session (back up runs/ first).")

        self.name = model_id.split("/")[-1]
        self.model_id = model_id
        self.via = "local-4bit" if quantised else "local-fp16"
        self.max_tokens = max_tokens

        load = {"device_map": "auto", "torch_dtype": torch.float16}
        if quantised:
            load["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True)

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, **load)
        self.model.eval()

        # A hosted API enforces a schema at its own sampler. Locally we do it ourselves
        # with a logits processor, which is only possible *because* the model runs here:
        # a remote sampler cannot be constrained by the caller. This is the mitigation
        # for the failure that cost this model 40% of rows on a nested schema.
        self.schema = schema
        self.processors = None
        if schema:
            try:
                from transformers import LogitsProcessorList
                from outlines.processors import JSONLogitsProcessor
                from outlines.models.transformers import TransformerTokenizer
                self.processors = LogitsProcessorList([
                    JSONLogitsProcessor(schema, TransformerTokenizer(self.tokenizer))])
                self.schema_enforced = True
            except Exception as exc:
                print(f"constrained decoding unavailable ({type(exc).__name__}); "
                      f"falling back to prompting for JSON")
                self.schema_enforced = False
        else:
            self.schema_enforced = False

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
                pad_token_id=self.tokenizer.eos_token_id,
                **({"logits_processor": self.processors} if self.processors else {}))
        generated = output[0][inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(generated, skip_special_tokens=True), {
            "input_tokens": int(inputs["input_ids"].shape[1]),
            "output_tokens": int(generated.shape[0]),
            "seconds": round(time.time() - started, 2),
            "retries": 0,
            "schema_enforced": bool(self.schema_enforced),
        }


class ReplayModel:
    """Replays a recorded run, including its original cost and latency.

    A recording stores the reply and the usage that produced it, so a replayed
    comparison reports the tokens and wall-clock of the live call rather than zeros.
    Without that, a table mixing replayed and live models silently understates the
    replayed ones to nothing.

    Recordings written before usage was stored hold a bare string; those replay with
    zeros and are reported as missing telemetry rather than as free.
    """

    def __init__(self, responses, name="replay"):
        self.responses = responses
        self.name = name
        self.via = "replay"
        self.calls = 0

    def generate(self, system, user):
        entry = self.responses.get(str(self.calls))
        self.calls += 1
        if entry is None:
            return '{"services": []}', {"input_tokens": 0, "output_tokens": 0,
                                        "seconds": 0.0, "retries": 0,
                                        "schema_enforced": False, "telemetry": "missing"}
        if isinstance(entry, str):
            return entry, {"input_tokens": 0, "output_tokens": 0, "seconds": 0.0,
                           "retries": 0, "schema_enforced": False, "telemetry": "missing"}
        usage = dict(entry.get("usage") or {})
        usage.setdefault("input_tokens", 0)
        usage.setdefault("output_tokens", 0)
        usage.setdefault("seconds", 0.0)
        usage.setdefault("retries", 0)
        usage.setdefault("schema_enforced", False)
        usage["telemetry"] = "recorded"
        return entry.get("reply", ""), usage


def parse_json(text):
    """Extract a JSON object from a model reply. Returns (object, error).

    Accepts an already-decoded object as well as raw text. A recording stores the
    reply beside its usage, and an older replayer handed the whole record through
    here; tolerating that is cheaper than requiring every caller to unwrap first.
    """
    if isinstance(text, dict) and "reply" in text:
        text = text["reply"]
    if isinstance(text, (dict, list)):
        return text, None
    if not isinstance(text, str):
        return None, f"reply is {type(text).__name__}, not text"
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
