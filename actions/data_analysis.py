"""Analyse CSV/Excel (master-doc §4.2)."""

from __future__ import annotations

import logging
from pathlib import Path

import app_paths

logger = logging.getLogger(__name__)


def load_dataframe(file_path: str):
    import pandas as pd

    path = Path(file_path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def get_summary(df) -> str:
    import pandas as pd

    lines = [
        f"Lignes: {len(df)}, Colonnes: {list(df.columns)}",
        f"Types:\n{df.dtypes.to_string()}",
        f"Describe:\n{df.describe(include='all').to_string()}",
        f"Aperçu:\n{df.head(20).to_string()}",
    ]
    return "\n\n".join(lines)


def answer_question(df, question: str) -> str:
    import pandas as pd

    safe_builtins = {"len": len, "sum": sum, "min": min, "max": max, "round": round, "str": str, "int": int, "float": float}
    namespace = {"df": df, "pd": pd, "result": None, "__builtins__": safe_builtins}
    code = f"result = None\n# {question}\n"
    try:
        import llm

        prompt = (
            f"Génère UNIQUEMENT du code Python utilisant df (pandas DataFrame) pour: {question}\n"
            f"Résumé données:\n{get_summary(df)[:3000]}\n"
            "Assigne le résultat à la variable result. Pas d'import os/subprocess."
        )
        raw = llm.ask_return_text(prompt)
        code += raw
        exec(code, namespace, namespace)
        result = namespace.get("result")
        return str(result) if result is not None else "Aucun résultat."
    except Exception as exc:
        logger.error("data_analysis error: %s", exc)
        return f"Erreur analyse : {exc}"


def analyze_file(file_path: str, question: str = "") -> str:
    df = load_dataframe(file_path)
    if question:
        return answer_question(df, question)
    return get_summary(df)
