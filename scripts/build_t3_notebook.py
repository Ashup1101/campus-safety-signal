"""Generate notebooks/t3_lite_qlora.ipynb, the Kaggle notebook for T3-lite.

The notebook embeds src/campus_safety/t3/schema.py and score.py verbatim, so the prompt, target
format, and scoring on Kaggle are the same code as locally. Re-run after changing either file;
a test fails if the committed notebook is out of date.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NOTEBOOK = REPO / "notebooks" / "t3_lite_qlora.ipynb"
T3 = REPO / "src" / "campus_safety" / "t3"


def _embedded(name: str) -> str:
    source = (T3 / name).read_text()
    # Inside the notebook both files share one namespace.
    return re.sub(r"^from campus_safety\.t3\.schema import .*\n", "", source, flags=re.M)


def _cell(index: int, kind: str, text: str) -> dict[str, object]:
    lines = text.strip("\n").splitlines(keepends=True)
    # Sequential ids and sorted keys: exactly the form nbstripout leaves, so the hook is a no-op.
    cell: dict[str, object] = {"cell_type": kind, "id": str(index), "metadata": {}, "source": lines}
    if kind == "code":
        cell |= {"execution_count": None, "outputs": []}
    return cell


CELLS = [
    (
        "markdown",
        """
# T3-lite: QLoRA fine-tune of Qwen2.5-1.5B-Instruct for crime log extraction

Input: the private Kaggle dataset built by `uv run t3 export` (train / validation / test /
legacy_holdout JSONL). Settings: GPU T4 x1 (or P100), Internet on.

Steps: zero-shot baseline -> QLoRA fine-tune -> evaluate (test + legacy_holdout) -> export GGUF.
Cells print counts and metrics only; per-field error examples go to files in
`/kaggle/working/t3_outputs/` (download that folder when the run finishes).
""",
    ),
    (
        "code",
        """
%pip install -q "unsloth==2026.10.6" "unsloth-zoo==2026.10.6"
""",
    ),
    (
        "code",
        """
import glob, json, os, platform, time
from pathlib import Path

MODEL = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"  # Apache-2.0, 4-bit build of the base below
MODEL_REVISION = "d2f2dd02b071701d5100a04a7a49d6fb0bd305b7"
BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"  # Apache-2.0
BASE_REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"
MAX_SEQ = 2048
HYPER = dict(
    lora_r=16, lora_alpha=16, lora_dropout=0.0, learning_rate=2e-4, epochs=1,
    batch_size=8, grad_accum=2, warmup_ratio=0.03, weight_decay=0.01,
    lr_scheduler="linear", optimizer="adamw_8bit", seed=3407, max_new_tokens=192,
)
DATA = Path(sorted(glob.glob("/kaggle/input/**/train.jsonl", recursive=True))[0]).parent
OUT = Path("/kaggle/working/t3_outputs")
OUT.mkdir(parents=True, exist_ok=True)

def load(name):
    with open(DATA / f"{name}.jsonl") as f:
        return [json.loads(line) for line in f]

splits = {name: load(name) for name in ("train", "validation", "test", "legacy_holdout")}
print({name: len(rows) for name, rows in splits.items()})
""",
    ),
    ("code", "# --- campus_safety/t3/schema.py (embedded) ---\n" + _embedded("schema.py")),
    ("code", "# --- campus_safety/t3/score.py (embedded) ---\n" + _embedded("score.py")),
    (
        "code",
        """
import torch
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template, train_on_responses_only

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=MODEL, revision=MODEL_REVISION, max_seq_length=MAX_SEQ, load_in_4bit=True
)
tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
GPU = torch.cuda.get_device_name(0)
print("GPU:", GPU)

def generate(rows, batch=16):
    FastLanguageModel.for_inference(model)
    tokenizer.padding_side = "left"
    outputs = []
    for i in range(0, len(rows), batch):
        prompts = [
            tokenizer.apply_chat_template(
                messages(r["source"]), tokenize=False, add_generation_prompt=True
            )
            for r in rows[i : i + batch]
        ]
        encoded = tokenizer(prompts, return_tensors="pt", padding=True).to("cuda")
        with torch.no_grad():
            generated = model.generate(
                **encoded, max_new_tokens=HYPER["max_new_tokens"], do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
            )
        new_tokens = generated[:, encoded["input_ids"].shape[1] :]
        outputs += tokenizer.batch_decode(new_tokens, skip_special_tokens=True)
    return outputs

def evaluate(label):
    results = {}
    for name in ("test", "legacy_holdout"):
        rows = splits[name]
        start = time.time()
        outputs = generate(rows)
        seconds = time.time() - start
        report = score(outputs, [r["target"] for r in rows])
        results[name] = report.summary() | {"seconds": seconds}
        with open(OUT / f"predictions_{label}_{name}.jsonl", "w") as f:
            for row, text in zip(rows, outputs):
                f.write(json.dumps({"pair_id": row["pair_id"], "output": text}) + "\\n")
        examples = {}
        for field_name, indices in report.errors.items():
            examples[field_name] = [
                {
                    "pair_id": rows[i]["pair_id"],
                    "layout": rows[i]["layout"],
                    "expected": rows[i]["target"].get(field_name),
                    "predicted": (parse_output(outputs[i]) or {}).get(field_name),
                }
                for i in indices[:5]
            ]
        counts = {k: len(v) for k, v in report.errors.items()}
        with open(OUT / f"errors_{label}_{name}.json", "w") as f:
            json.dump({"error_counts": counts, "examples": examples}, f, indent=2)
        print(label, name, {k: round(v, 4) for k, v in results[name].items()})
    return results

metrics = {"baseline": evaluate("baseline")}
""",
    ),
    (
        "code",
        """
from datasets import Dataset
from trl import SFTConfig, SFTTrainer

model = FastLanguageModel.get_peft_model(
    model, r=HYPER["lora_r"], lora_alpha=HYPER["lora_alpha"], lora_dropout=HYPER["lora_dropout"],
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    bias="none", use_gradient_checkpointing="unsloth", random_state=HYPER["seed"],
)
FastLanguageModel.for_training(model)
tokenizer.padding_side = "right"

def as_text(rows):
    return Dataset.from_list([
        {"text": tokenizer.apply_chat_template(messages(r["source"], r["target"]), tokenize=False)}
        for r in rows
    ])

config = SFTConfig(
    output_dir="checkpoints", dataset_text_field="text", max_seq_length=MAX_SEQ,
    per_device_train_batch_size=HYPER["batch_size"],
    gradient_accumulation_steps=HYPER["grad_accum"],
    num_train_epochs=HYPER["epochs"], learning_rate=HYPER["learning_rate"],
    warmup_ratio=HYPER["warmup_ratio"], weight_decay=HYPER["weight_decay"],
    lr_scheduler_type=HYPER["lr_scheduler"], optim=HYPER["optimizer"], seed=HYPER["seed"],
    logging_steps=25, eval_strategy="epoch", report_to="none",
)
trainer = SFTTrainer(
    model=model, processing_class=tokenizer, args=config,
    train_dataset=as_text(splits["train"]), eval_dataset=as_text(splits["validation"]),
)
trainer = train_on_responses_only(
    trainer, instruction_part="<|im_start|>user\\n", response_part="<|im_start|>assistant\\n"
)
start = time.time()
train_result = trainer.train()
train_seconds = time.time() - start
eval_result = trainer.evaluate()
print({
    "train_seconds": round(train_seconds),
    "train_loss": train_result.training_loss,
    "eval_loss": eval_result.get("eval_loss"),
})
""",
    ),
    (
        "code",
        """
metrics["finetuned"] = evaluate("finetuned")
model.save_pretrained(OUT / "lora_adapter")
tokenizer.save_pretrained(OUT / "lora_adapter")
start = time.time()
model.save_pretrained_gguf(str(OUT / "gguf"), tokenizer, quantization_method="q4_k_m")
gguf_seconds = time.time() - start

import importlib.metadata as md
run_info = {
    "model": MODEL, "model_revision": MODEL_REVISION, "base_model": BASE_MODEL,
    "base_revision": BASE_REVISION, "license": "apache-2.0", "gpu": GPU, "hyperparameters": HYPER,
    "max_seq_length": MAX_SEQ, "rows": {k: len(v) for k, v in splits.items()},
    "train_seconds": train_seconds, "train_loss": train_result.training_loss,
    "eval_loss": eval_result.get("eval_loss"), "gguf_seconds": gguf_seconds,
    "versions": {
        p: md.version(p)
        for p in ("unsloth", "unsloth_zoo", "trl", "transformers", "peft", "torch", "bitsandbytes")
    },
    "python": platform.python_version(),
}
with open(OUT / "metrics.json", "w") as f:
    json.dump(metrics, f, indent=2)
with open(OUT / "run_info.json", "w") as f:
    json.dump(run_info, f, indent=2)
print(sorted(p.name for p in OUT.rglob("*") if p.is_file()))
""",
    ),
]


def build() -> str:
    notebook = {
        "cells": [_cell(index, kind, text) for index, (kind, text) in enumerate(CELLS)],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(notebook, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> None:
    NOTEBOOK.parent.mkdir(parents=True, exist_ok=True)
    NOTEBOOK.write_text(build())
    print(f"wrote {NOTEBOOK.relative_to(REPO)}")


if __name__ == "__main__":
    main()
