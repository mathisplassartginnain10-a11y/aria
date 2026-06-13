import json
import logging
import re
from pathlib import Path

import requests
import sympy
import yaml
import app_paths
from scipy import stats
from sympy import (
    E,
    Integral,
    Matrix,
    Rational,
    Symbol,
    diff,
    expand,
    factor,
    integrate,
    limit,
    oo,
    simplify,
    solve,
    sympify,
)

logger = logging.getLogger(__name__)

_CONFIG_PATH = app_paths.config_path()
_PROMPTS_DIR = app_paths.prompts_dir()

with _CONFIG_PATH.open("r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

MODEL = _config.get("model", "qwen3:14b")
MATH_PRECISION = int(_config.get("math_precision", 10))
MATH_MODE_ENABLED = _config.get("math_mode_enabled", True)
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

MATH_SYSTEM_PROMPT = (_PROMPTS_DIR / "math_system.txt").read_text(encoding="utf-8")


def _ollama_chat(system_prompt: str, user_message: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
    }
    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()["message"]["content"].strip()
    except (requests.RequestException, KeyError, json.JSONDecodeError):
        logger.exception("Ollama math request failed")
        return "Impossible de contacter Ollama pour cette question de maths."


def convert_speech_to_math(text: str) -> str:
    replacements = [
        (r"\bx au carré\b", "x**2"),
        (r"\bx au cube\b", "x**3"),
        (r"\bx carré\b", "x**2"),
        (r"\bau carré\b", "**2"),
        (r"\bplus\b", "+"),
        (r"\bmoins\b", "-"),
        (r"\bfois\b", "*"),
        (r"\bdivisé par\b", "/"),
        (r"\bracine carrée de\b", "sqrt("),
        (r"\bracine de\b", "sqrt("),
        (r"\be puissance x\b", "exp(x)"),
        (r"\be puissance\b", "exp("),
        (r"\bpi\b", "pi"),
        (r"\bsinus\b", "sin"),
        (r"\bcosinus\b", "cos"),
        (r"\btangente\b", "tan"),
        (r"\blogarithme népérien\b", "log"),
        (r"\blog\b", "log"),
    ]
    result = text.lower().strip()
    for pattern, repl in replacements:
        result = re.sub(pattern, repl, result, flags=re.I)
    result = result.replace("=", "==") if "=" in result and "==" not in result else result
    open_sqrt = result.count("sqrt(") - result.count(")")
    if open_sqrt > 0:
        result += ")" * open_sqrt
    return result


def format_math_for_speech(expr) -> str:
    s = str(simplify(expr))
    replacements = [
        (r"\*\*", " puissance "),
        (r"\*", " fois "),
        (r"sqrt\(([^)]+)\)", r"racine carrée de \1"),
        (r"sin\(([^)]+)\)", r"sinus de \1"),
        (r"cos\(([^)]+)\)", r"cosinus de \1"),
        (r"tan\(([^)]+)\)", r"tangente de \1"),
        (r"log\(([^)]+)\)", r"logarithme de \1"),
        (r"exp\(([^)]+)\)", r"e puissance \1"),
        (r"pi", "pi"),
        (r"\+", " plus "),
        (r"-", " moins "),
        (r"/", " sur "),
    ]
    for pattern, repl in replacements:
        s = re.sub(pattern, repl, s)
    s = re.sub(r"(\d+)/(\d+)", lambda m: f"{m.group(1)} sur {m.group(2)}", s)
    if isinstance(expr, Rational) or "/" in str(expr):
        try:
            val = float(expr.evalf())
            if abs(val - 0.5) < 1e-9:
                return "un demi"
        except Exception:
            pass
    return " ".join(s.split())


def calculate_exact(expression: str) -> str:
    try:
        expr_str = convert_speech_to_math(expression)
        expr_str = re.sub(r"^(calcule|combien font|évalue)\s*", "", expr_str, flags=re.I)
        expr = sympify(expr_str)
        exact = simplify(expr)
        approx = float(expr.evalf(MATH_PRECISION))
        exact_speech = format_math_for_speech(exact)
        return f"Résultat exact : {exact_speech}, soit environ {approx:.{min(MATH_PRECISION, 6)}g}."
    except Exception:
        logger.exception("calculate_exact failed for: %s", expression)
        return f"Impossible de calculer : {expression}"


def derive(expression: str, variable: str = "x") -> str:
    try:
        expr_str = re.sub(r".*d[ée]riv[ée]e de\s*", "", expression, flags=re.I)
        expr_str = convert_speech_to_math(expr_str)
        var = Symbol(variable)
        expr = sympify(expr_str)
        result = simplify(diff(expr, var))
        return f"La dérivée de {format_math_for_speech(expr)} par rapport à {variable} est {format_math_for_speech(result)}."
    except Exception:
        logger.exception("derive failed")
        return "Impossible de calculer cette dérivée."


def integrate_expr(expression: str, variable: str = "x", a=None, b=None) -> str:
    try:
        expr_str = re.sub(r".*int[èe]gre\s*", "", expression, flags=re.I)
        bounds = re.search(r"entre\s*([\d./pi\s+-]+)\s*et\s*([\d./pi\s+-]+)", expr_str, re.I)
        if bounds:
            a_str, b_str = bounds.group(1).strip(), bounds.group(2).strip()
            expr_str = expr_str[: bounds.start()]
            a = sympify(convert_speech_to_math(a_str))
            b = sympify(convert_speech_to_math(b_str))
        expr_str = convert_speech_to_math(expr_str)
        var = Symbol(variable)
        expr = sympify(expr_str)
        if a is not None and b is not None:
            result = simplify(integrate(expr, (var, a, b)))
            return f"L'intégrale de {format_math_for_speech(expr)} entre {a} et {b} vaut {format_math_for_speech(result)}."
        result = simplify(integrate(expr, var))
        return f"Une primitive de {format_math_for_speech(expr)} est {format_math_for_speech(result)}."
    except Exception:
        logger.exception("integrate failed")
        return "Impossible de calculer cette intégrale."


def solve_equation(equation: str) -> str:
    try:
        eq_str = re.sub(r".*r[ée]sous\s*", "", equation, flags=re.I)
        eq_str = convert_speech_to_math(eq_str)
        if "==" not in eq_str and "=" in eq_str:
            eq_str = eq_str.replace("=", "==", 1)
        x = Symbol("x")
        if "==" in eq_str:
            lhs, rhs = eq_str.split("==", 1)
            eq = sympify(lhs) - sympify(rhs)
        else:
            eq = sympify(eq_str)
        solutions = solve(eq, x)
        if not solutions:
            return "Pas de solution réelle trouvée."
        sol_str = ", ".join(format_math_for_speech(s) for s in solutions)
        return f"Solutions : {sol_str}."
    except Exception:
        logger.exception("solve_equation failed")
        return "Impossible de résoudre cette équation."


def solve_system(equations: list[str]) -> str:
    try:
        syms = symbols_from_count(len(equations))
        eqs = []
        for i, eq_str in enumerate(equations):
            eq_str = convert_speech_to_math(eq_str)
            if "==" in eq_str:
                lhs, rhs = eq_str.split("==", 1)
                eqs.append(sympify(lhs) - sympify(rhs))
            else:
                eqs.append(sympify(eq_str))
        solutions = solve(eqs, syms)
        if not solutions:
            return "Pas de solution pour ce système."
        if isinstance(solutions, dict):
            parts = [f"{k} = {format_math_for_speech(v)}" for k, v in solutions.items()]
            return "Solutions : " + ", ".join(parts) + "."
        return f"Solutions : {solutions}."
    except Exception:
        logger.exception("solve_system failed")
        return "Impossible de résoudre ce système."


def symbols_from_count(n: int):
    names = ["x", "y", "z", "t"]
    return [Symbol(names[i]) for i in range(min(n, len(names)))]


def factor_expr(expression: str) -> str:
    try:
        expr_str = re.sub(r".*factorise\s*", "", expression, flags=re.I)
        expr = sympify(convert_speech_to_math(expr_str))
        result = factor(expr)
        return f"Factorisation : {format_math_for_speech(result)}."
    except Exception:
        logger.exception("factor failed")
        return "Impossible de factoriser."


def expand_expr(expression: str) -> str:
    try:
        expr_str = re.sub(r".*d[ée]veloppe\s*", "", expression, flags=re.I)
        expr = sympify(convert_speech_to_math(expr_str))
        result = expand(expr)
        return f"Développement : {format_math_for_speech(result)}."
    except Exception:
        logger.exception("expand failed")
        return "Impossible de développer."


def limit_expr(expression: str, variable: str = "x", point=None) -> str:
    try:
        expr_str = re.sub(r".*limite de\s*", "", expression, flags=re.I)
        point_match = re.search(r"quand\s*(\w+)\s*tend vers\s*([\d.+-]+|infini|infinity|oo)", expr_str, re.I)
        if point_match:
            variable = point_match.group(1)
            pt_str = point_match.group(2)
            expr_str = expr_str[: point_match.start()]
            point = oo if pt_str.lower() in ("infini", "infinity", "oo") else sympify(pt_str)
        expr_str = convert_speech_to_math(expr_str)
        var = Symbol(variable)
        expr = sympify(expr_str)
        if point is None:
            point = 0
        result = simplify(limit(expr, var, point))
        return f"La limite vaut {format_math_for_speech(result)}."
    except Exception:
        logger.exception("limit failed")
        return "Impossible de calculer cette limite."


def matrix_operations(matrix_str: str, operation: str = "determinant") -> str:
    try:
        rows = re.findall(r"\[([^\]]+)\]", matrix_str)
        if not rows:
            nums = re.findall(r"-?\d+(?:\.\d+)?", matrix_str)
            size = int(len(nums) ** 0.5)
            data = [[sympify(nums[i * size + j]) for j in range(size)] for i in range(size)]
        else:
            data = [[sympify(x.strip()) for x in row.split(",")] for row in rows]
        mat = Matrix(data)
        op = operation.lower()
        if "inverse" in op:
            result = mat.inv()
            return f"Inverse : {result}."
        if "propre" in op or "eigen" in op:
            eigenvals = mat.eigenvals()
            return f"Valeurs propres : {eigenvals}."
        det = mat.det()
        return f"Déterminant : {format_math_for_speech(det)}."
    except Exception:
        logger.exception("matrix_operations failed")
        return "Opération matricielle impossible."


def suite_arithmetique(u0: float, r: float, n: int) -> str:
    un = u0 + (n - 1) * r
    somme = n * (u0 + un) / 2
    return (
        f"Suite arithmétique : u0={u0}, raison {r}. "
        f"Terme u{n} = {un}. Somme des {n} premiers termes = {somme}."
    )


def suite_geometrique(u0: float, q: float, n: int) -> str:
    un = u0 * (q ** (n - 1))
    if abs(q - 1) < 1e-9:
        somme = n * u0
    else:
        somme = u0 * (1 - q**n) / (1 - q)
    limite = ""
    if abs(q) < 1:
        limite = f" La limite de la suite est {u0 / (1 - q) if abs(q - 1) > 1e-9 else 'non définie'}."
    return f"Suite géométrique : u0={u0}, raison {q}. Terme u{n} = {un:.4g}. Somme = {somme:.4g}.{limite}"


def loi_binomiale(n: int, p: float, k: int | None = None, mode: str = "exact") -> str:
    dist = stats.binom(n, p)
    esp = n * p
    var = n * p * (1 - p)
    if mode == "exact" and k is not None:
        prob = dist.pmf(k)
        return f"P(X={k}) = {prob:.4f}. Espérance {esp:.2f}, variance {var:.2f}."
    if mode == "inf" and k is not None:
        prob = dist.cdf(k)
        return f"P(X≤{k}) = {prob:.4f}. Espérance {esp:.2f}, variance {var:.2f}."
    if mode == "sup" and k is not None:
        prob = 1 - dist.cdf(k - 1)
        return f"P(X≥{k}) = {prob:.4f}. Espérance {esp:.2f}, variance {var:.2f}."
    return f"Loi binomiale n={n}, p={p}. Espérance {esp:.2f}, écart-type {var**0.5:.2f}."


def _is_pure_calculation(text: str) -> bool:
    keywords = ["dérivée", "derive", "intègre", "integrale", "résous", "factorise", "limite", "suite", "binomiale", "matrice"]
    return not any(k in text.lower() for k in keywords)


def handle(text: str) -> str:
    t = text.lower()
    if "suite arithmétique" in t or "suite arithmetique" in t:
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
        if len(nums) >= 3:
            return suite_arithmetique(nums[0], nums[1], int(nums[2]))
    if "suite géométrique" in t or "suite geometrique" in t:
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
        if len(nums) >= 3:
            return suite_geometrique(nums[0], nums[1], int(nums[2]))
    if "binomiale" in t or "binom" in t:
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
        if len(nums) >= 2:
            n, p = int(nums[0]), nums[1] if nums[1] <= 1 else nums[1] / 100
            k = int(nums[2]) if len(nums) > 2 else None
            mode = "inf" if "au plus" in t or "inférieur" in t else "sup" if "au moins" in t else "exact"
            return loi_binomiale(n, p, k, mode)
    if "factorise" in t:
        return factor_expr(text)
    if "développe" in t or "developpe" in t:
        return expand_expr(text)
    if "limite" in t:
        return limit_expr(text)
    if "intègre" in t or "integrale" in t:
        return integrate_expr(text)
    if "dérivée" in t or "derive" in t:
        return derive(text)
    if "résous" in t or "resous" in t or "=" in text:
        return solve_equation(text)
    if "matrice" in t:
        return matrix_operations(text)
    if _is_pure_calculation(text):
        result = calculate_exact(text)
        if "Impossible" not in result:
            return result
    return solve(text)


def solve(problem_text: str) -> str:
    if not MATH_MODE_ENABLED:
        return "Le mode maths expert est désactivé."
    if _is_pure_calculation(problem_text):
        exact = calculate_exact(problem_text)
        if "Impossible" not in exact:
            return exact
    response = _ollama_chat(MATH_SYSTEM_PROMPT, problem_text)
    cleaned = response.replace("²", " au carré ").replace("³", " au cube ")
    cleaned = re.sub(r"(\d)/(\d)", r"\1 sur \2", cleaned)
    return cleaned