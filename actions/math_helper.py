import logging
import re

import sympy
from sympy import Symbol, diff, integrate, sympify, solve
import app_paths

logger = logging.getLogger(__name__)

CONVERSIONS = {
    ("km/h", "nœuds"): lambda v: v / 1.852,
    ("nœuds", "km/h"): lambda v: v * 1.852,
    ("nm", "km"): lambda v: v * 1.852,
    ("km", "nm"): lambda v: v / 1.852,
    ("°c", "°f"): lambda v: v * 9 / 5 + 32,
    ("°f", "°c"): lambda v: (v - 32) * 5 / 9,
    ("kg", "lb"): lambda v: v * 2.20462,
    ("lb", "kg"): lambda v: v / 2.20462,
    ("m", "ft"): lambda v: v * 3.28084,
    ("ft", "m"): lambda v: v / 3.28084,
}


def _safe_eval(expression: str) -> float | None:
    allowed = set("0123456789+-*/().,% ")
    cleaned = expression.replace(",", ".")
    if not all(c in allowed for c in cleaned):
        return None
    try:
        return float(eval(cleaned, {"__builtins__": {}}, {}))
    except Exception:
        return None


def calculate(expression: str) -> str:
    pct = re.search(r"(\d+(?:\.\d+)?)\s*%\s*de\s*(\d+(?:\.\d+)?)", expression, re.I)
    if pct:
        result = float(pct.group(1)) / 100 * float(pct.group(2))
        return f"Résultat : {result:.2f}."

    cleaned = re.sub(r"combien font\s*", "", expression, flags=re.I).strip()
    result = _safe_eval(cleaned)
    if result is not None:
        return f"Résultat : {result:.4g}."

    try:
        expr = sympify(cleaned.replace("^", "**"))
        val = float(expr.evalf())
        return f"Résultat : {val:.4g}."
    except Exception:
        logger.exception("Calculation failed")
        return "Expression non reconnue."


def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    from_u = from_unit.lower().strip()
    to_u = to_unit.lower().strip()
    key = (from_u, to_u)
    if key not in CONVERSIONS:
        return f"Conversion {from_unit} vers {to_unit} non supportée."
    result = CONVERSIONS[key](float(value))
    return f"{value} {from_unit} = {result:.2f} {to_unit}."


def parse_conversion(text: str) -> str:
    match = re.search(
        r"convertis?\s*(\d+(?:\.\d+)?)\s*(\S+)\s*(?:en|vers|to)\s*(\S+)",
        text,
        re.I,
    )
    if match:
        return convert_units(float(match.group(1)), match.group(2), match.group(3))
    return "Conversion non reconnue."


def solve_equation(equation: str) -> str:
    try:
        cleaned = equation.replace("=", "-(") + ")" if "=" in equation else equation
        cleaned = cleaned.replace("²", "**2").replace("^", "**")
        x = Symbol("x")
        solutions = solve(sympify(cleaned), x)
        if not solutions:
            return "Pas de solution trouvée."
        return f"Solutions : {', '.join(str(s) for s in solutions)}."
    except Exception:
        logger.exception("Equation solve failed")
        return "Équation non reconnue."


def derivative(expression: str, variable: str = "x") -> str:
    try:
        expr = re.sub(r"d[ée]rive\s*f?\(?x?\)?\s*=\s*", "", expression, flags=re.I)
        expr = expr.replace("²", "**2").replace("^", "**")
        var = Symbol(variable)
        result = diff(sympify(expr), var)
        return f"Dérivée : {result}."
    except Exception:
        logger.exception("Derivative failed")
        return "Dérivée non calculable."


def integral(expression: str, variable: str = "x") -> str:
    try:
        expr = expression.replace("²", "**2").replace("^", "**")
        var = Symbol(variable)
        result = integrate(sympify(expr), var)
        return f"Intégrale : {result}."
    except Exception:
        logger.exception("Integral failed")
        return "Intégrale non calculable."


def handle(text: str) -> str:
    text_lower = text.lower()
    if "convertis" in text_lower:
        return parse_conversion(text)
    if "dérive" in text_lower or "derive" in text_lower:
        return derivative(text)
    if "résous" in text_lower or "resous" in text_lower or "=" in text:
        return solve_equation(text)
    if "intègre" in text_lower or "integrale" in text_lower:
        return integral(text)
    return calculate(text)