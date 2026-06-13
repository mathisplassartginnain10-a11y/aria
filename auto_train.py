"""
Lance un ré-entraînement automatique quand 50 nouveaux exemples sont collectés.
Tourne en arrière-plan.
"""
import logging
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DATASET_PATH = Path("data/fine_tune_dataset.jsonl")
LAST_COUNT_PATH = Path("data/last_train_count.txt")
MIN_NEW_EXAMPLES = 50  # Ré-entraîne tous les 50 nouveaux exemples


def get_dataset_count() -> int:
    if not DATASET_PATH.exists():
        return 0
    return sum(1 for _ in DATASET_PATH.open(encoding="utf-8"))


def get_last_train_count() -> int:
    if LAST_COUNT_PATH.exists():
        return int(LAST_COUNT_PATH.read_text(encoding="utf-8"))
    return 0


def save_last_train_count(count: int) -> None:
    LAST_COUNT_PATH.write_text(str(count), encoding="utf-8")


def watch_and_train() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    python_exe = Path(".venv/Scripts/python.exe")
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    logger.info("Auto-train démarré — vérifie toutes les heures")
    while True:
        try:
            current = get_dataset_count()
            last = get_last_train_count()
            new_examples = current - last
            logger.info(
                "Dataset: %d total, %d nouveaux depuis dernier entraînement",
                current,
                new_examples,
            )

            if new_examples >= MIN_NEW_EXAMPLES and current >= 10:
                logger.info("🚀 %d nouveaux exemples — lancement entraînement...", new_examples)
                result = subprocess.run(
                    [str(python_exe), "train_aria.py"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    save_last_train_count(current)
                    logger.info("✅ Entraînement terminé")
                else:
                    logger.error("❌ Entraînement échoué: %s", result.stderr)
        except Exception as e:
            logger.error("Auto-train error: %s", e)

        time.sleep(3600)  # Vérifie toutes les heures


if __name__ == "__main__":
    watch_and_train()
