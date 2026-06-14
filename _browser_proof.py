import pathlib
from playwright.sync_api import sync_playwright

HTML = pathlib.Path(r"C:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal\ui\index.html").resolve().as_uri()
SHOT = r"C:\Users\mathi\OneDrive\Documents\assistant-ia\assistant-vocal\_ui_shot.png"


def test_typing(p, channel):
    try:
        b = p.chromium.launch(channel=channel, headless=True)
    except Exception as e:
        return f"LAUNCH FAIL: {type(e).__name__}: {str(e)[:80]}", ""
    try:
        pg = b.new_page()
        pg.set_content("<textarea id=t style='width:320px;height:80px'></textarea>"
                       "<div id=c contenteditable style='border:1px solid'></div>")
        pg.click("#t")
        pg.keyboard.type(f"Bonjour ARIA ({channel})")
        v = pg.input_value("#t")
        pg.click("#c")
        pg.keyboard.type("edition ok")
        cv = pg.inner_text("#c")
        return v, cv
    finally:
        b.close()


with sync_playwright() as p:
    print("=== PREUVE : ECRITURE DANS CHROME ET EDGE ===")
    for ch in ("chrome", "msedge"):
        v, cv = test_typing(p, ch)
        ok = "OK  " if str(v).startswith("Bonjour ARIA") else "FAIL"
        print(f"  [{ok}] {ch:7} -> textarea={v!r}  contenteditable={cv!r}")

    print("\n=== CAPTURE UI (alignement) ===")
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1366, "height": 860})
    pg.goto(HTML, wait_until="load")
    pg.wait_for_timeout(1400)
    try:
        pg.evaluate(
            "() => {"
            "aria.addUserBubble('Ouvre YouTube dans Edge');"
            "aria.appendToken('Voila, j ouvre YouTube dans Edge pour toi. ');"
            "aria.appendToken('Tu peux aussi me demander d ecrire dans un Google Doc.');"
            "aria.finalizeMessage();"
            "aria.setStatus('listening');"
            "}"
        )
    except Exception as e:
        print("  populate err:", e)
    pg.wait_for_timeout(600)
    pg.screenshot(path=SHOT)
    b.close()
    print("  Screenshot ->", SHOT)
