"""Small server-owned sign-in page, available before loading the application."""

from html import escape


def sign_in_page(message: str = "") -> str:
    notice = f'<p role="alert">{escape(message)}</p>' if message else ""
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Sign in · CatLabel</title>
<style>
body {{ font: 1rem system-ui, sans-serif; color: #171717; background: #f5f5f5;
margin: 0; min-height: 100vh; display: grid; place-items: center; }}
main {{ background: white; padding: 2rem; border: 1px solid #d4d4d4; border-radius: 1rem;
width: min(24rem, calc(100vw - 6rem)); }}
label,input,button {{ display: block; box-sizing: border-box; width: 100%; }}
input,button {{ font: inherit; padding: .75rem; margin-top: .5rem; border-radius: .4rem; }}
input {{ border: 1px solid #737373; }} button {{ background: #1d4ed8; color: white;
border: 0; cursor: pointer; margin-top: 1rem; }}
input:focus-visible,button:focus-visible {{ outline: 3px solid #2563eb; outline-offset: 3px; }}
p {{ line-height: 1.5; }} [role=alert] {{ color: #b91c1c; }}
</style>
<main><h1>CatLabel</h1><p>This server requires an access token. Use the token configured
on the computer running CatLabel.</p>{notice}
<form method="post" action="/auth/login">
<label for="token">Access token</label>
<input id="token" name="token" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Open CatLabel</button>
</form><p>Your token stays out of the URL. Printing and AI settings remain behind this sign-in.</p>
</main></html>"""
