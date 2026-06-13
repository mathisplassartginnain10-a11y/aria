"""
Fine-tuning ARIA sur les conversations de l'utilisateur.
Utilise Unsloth + LoRA pour entraîner sur GPU (RTX 5080 16GB).
Lance : .venv\Scripts\python.exe train_aria.py
"""
import json
from pathlib import Path

DATASET_PATH = Path("data/fine_tune_dataset.jsonl")
OUTPUT_PATH = Path("data/aria_lora")
BASE_MODEL = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit"


def load_dataset():
    if not DATASET_PATH.exists():
        print(f"❌ Dataset introuvable: {DATASET_PATH}")
        print("   Utilise ARIA pendant quelques heures pour collecter des données.")
        return []
    examples = []
    with DATASET_PATH.open(encoding="utf-8") as f:
        for line in f:
            try:
                examples.append(json.loads(line))
            except Exception:
                pass
    print(f"✅ {len(examples)} exemples chargés")
    return examples


def format_for_training(examples):
    """Formate les données pour Unsloth."""
    formatted = []
    for ex in examples:
        msgs = ex.get("messages", [])
        if len(msgs) >= 2:
            formatted.append({
                "conversations": [
                    {"from": "human", "value": msgs[0]["content"]},
                    {"from": "gpt", "value": msgs[1]["content"]},
                ]
            })
    return formatted


def train():
    print("=== ENTRAÎNEMENT ARIA ===")
    print(f"Modèle de base: {BASE_MODEL}")

    examples = load_dataset()
    if len(examples) < 10:
        print(f"❌ Pas assez de données ({len(examples)}/10 minimum)")
        print("   Continue à utiliser ARIA pour collecter plus d'exemples.")
        return

    try:
        from unsloth import FastLanguageModel
        from trl import SFTTrainer
        from transformers import TrainingArguments
        from datasets import Dataset
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Lance: pip install unsloth trl datasets transformers")
        return

    print("📥 Chargement du modèle de base...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=2048,
        dtype=None,  # Auto-detect
        load_in_4bit=True,  # 4-bit pour tenir en 16GB VRAM
    )

    print("🔧 Application LoRA...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,  # Rank LoRA — plus élevé = meilleur mais plus lent
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    print("📊 Préparation dataset...")
    formatted = format_for_training(examples)
    dataset = Dataset.from_list(formatted)

    print(f"🚀 Début entraînement sur {len(formatted)} exemples...")
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="conversations",
        max_seq_length=2048,
        args=TrainingArguments(
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            warmup_steps=5,
            num_train_epochs=3,
            learning_rate=2e-4,
            fp16=True,
            logging_steps=10,
            output_dir=str(OUTPUT_PATH / "checkpoints"),
            optim="adamw_8bit",
            seed=42,
        ),
    )
    trainer.train()

    print("💾 Sauvegarde du modèle LoRA...")
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(OUTPUT_PATH))
    tokenizer.save_pretrained(str(OUTPUT_PATH))

    print("📦 Export GGUF pour Ollama...")
    model.save_pretrained_gguf(
        str(OUTPUT_PATH / "gguf"),
        tokenizer,
        quantization_method="q8_0",
    )

    gguf_file = list((OUTPUT_PATH / "gguf").glob("*.gguf"))[0]

    print("🤖 Création du Modelfile Ollama...")
    modelfile = f"""FROM {gguf_file}

SYSTEM \"\"\"
Tu es ARIA, l'assistant vocal personnel de Mathi.
Tu as été entraîné sur ses conversations réelles.
Tu connais ses projets, son style, ses préférences.
Tu réponds directement, sans introduction inutile.
\"\"\"

PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER repeat_penalty 1.1
"""
    modelfile_path = OUTPUT_PATH / "Modelfile"
    modelfile_path.write_text(modelfile, encoding="utf-8")

    print("🏗️ Enregistrement dans Ollama...")
    import subprocess

    subprocess.run(["ollama", "create", "aria-custom", "-f", str(modelfile_path)], check=False)

    print("\n✅ ENTRAÎNEMENT TERMINÉ !")
    print("   Nouveau modèle: aria-custom")
    print("   Pour l'utiliser: change model: aria-custom dans config.yaml")


if __name__ == "__main__":
    train()
