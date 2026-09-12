"""The only file that talks to a language model. Plain HTTP, retries when the endpoint
is busy, and a replay mode that reads saved replies from runs/ so the whole project
runs without an API key.
"""

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
                choice = payload["choices"][0]
                return choice["message"]["content"] or "", {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "seconds": round(time.time() - started, 2),
                    "retries": retries,
                    "schema_enforced": bool(self.schema_enforced),
                    "finish_reason": choice.get("finish_reason"),   # "length" means truncated
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


class RepairModel:
    """Replay a recording, but call the live model for chunks whose reply never parsed.

    A recorded run with one truncated reply is repaired with one call, not thirteen, and
    the merged replies are what gets recorded afterwards.
    """

    def __init__(self, recording, live, name):
        self.recording, self.live, self.name, self.via = recording, live, name, "repair"
        self.calls, self.repaired = 0, []

    def generate(self, system, user):
        entry = self.recording.get(str(self.calls))
        self.calls += 1
        if entry and parse_json(entry.get("reply", entry) if isinstance(entry, dict) else entry)[0] is not None:
            usage = dict(entry.get("usage", {})) if isinstance(entry, dict) else {}
            for k, v in (("input_tokens", 0), ("output_tokens", 0), ("seconds", 0.0),
                         ("retries", 0), ("schema_enforced", False)):
                usage.setdefault(k, v)
            usage["telemetry"] = "recorded"
            return (entry["reply"] if isinstance(entry, dict) else entry), usage
        self.repaired.append(self.calls - 1)
        return self.live.generate(system, user)


def recording_path(model_name, prompt_version, hospital):
    """runs/<model>__<prompt version>__<hospital>.json"""
    from src.config import RUNS
    return RUNS / f"{model_name}__{prompt_version}__{hospital}.json"


def load_recording(model_name, prompt_version, hospital):
    """A recorded run to replay, or None if this combination was never run."""
    path = recording_path(model_name, prompt_version, hospital)
    return json.load(open(path)) if path.exists() else None


def save_recording(record, model_name, prompt_version, hospital):
    path = recording_path(model_name, prompt_version, hospital)
    path.parent.mkdir(exist_ok=True)
    json.dump(record, open(path, "w"), indent=1)
    return path


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
