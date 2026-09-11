"""Qwen2.5-7B run locally, 4-bit, with constrained decoding where available.

Used only by the model comparison. The production path calls a hosted model.
"""

import time

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


def _build_constraint(schema, tokenizer):
    """A logits processor that admits only schema-valid JSON, or None.

    Outlines has moved this API across releases, so each known shape is tried in turn
    rather than pinning a version the Colab runtime may not resolve. Returning None is
    a supported outcome: generation falls back to prompting and the run is reported as
    unenforced rather than claiming a guarantee it does not have.
    """
    from transformers import LogitsProcessorList

    attempts = []

    try:
        from outlines.processors import JSONLogitsProcessor
        from outlines.models.transformers import TransformerTokenizer
        return LogitsProcessorList([JSONLogitsProcessor(schema, TransformerTokenizer(tokenizer))])
    except Exception as exc:
        attempts.append(f"outlines.processors+TransformerTokenizer: {type(exc).__name__}")

    try:
        from outlines.processors import JSONLogitsProcessor
        return LogitsProcessorList([JSONLogitsProcessor(schema, tokenizer)])
    except Exception as exc:
        attempts.append(f"outlines.processors bare tokenizer: {type(exc).__name__}")

    try:
        import outlines
        model = outlines.from_transformers(None, tokenizer)   # newer functional API
        return LogitsProcessorList([outlines.processors.JSONLogitsProcessor(schema, model.tokenizer)])
    except Exception as exc:
        attempts.append(f"outlines.from_transformers: {type(exc).__name__}")

    try:
        from lmformatenforcer import JsonSchemaParser
        from lmformatenforcer.integrations.transformers import (
            build_transformers_prefix_allowed_tokens_fn)
        from transformers import PrefixConstrainedLogitsProcessor
        fn = build_transformers_prefix_allowed_tokens_fn(tokenizer, JsonSchemaParser(schema))
        return LogitsProcessorList([PrefixConstrainedLogitsProcessor(fn, 1)])
    except Exception as exc:
        attempts.append(f"lm-format-enforcer: {type(exc).__name__}")

    print("constrained decoding unavailable; generation falls back to prompting")
    for a in attempts:
        print(f"    {a}")
    return None


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
        self.schema_enforced = False
        if schema:
            self.processors = _build_constraint(schema, self.tokenizer)
            self.schema_enforced = self.processors is not None

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


