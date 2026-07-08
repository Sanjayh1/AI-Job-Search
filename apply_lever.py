"""
Automated Lever job application.
Usage: python3 apply_lever.py <apply_url> <cover_letter_path>

Lever forms are consistent: first_name, last_name, email, phone,
resume (file), cover_letter (text), linkedin — no account required.
"""

import sys
import os
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

CONFIG_FILE = Path(__file__).parent / "config.json"
with open(CONFIG_FILE) as f:
    _candidate = json.load(f)["candidate"]

RESUME_PATH = _candidate["resume_path"]
_name_parts = _candidate["name"].split()

APPLICANT = {
    "first_name":  _name_parts[0],
    "last_name":   _name_parts[-1],
    "email":       _candidate["email"],
    "phone":       _candidate["phone"],
    "country":     "United States",
    "linkedin":    _candidate["linkedin"],
    "sponsorship": "Yes" if _candidate.get("requires_sponsorship") else "No",
}


def run(apply_url, cover_letter_path):
    cover_letter_text = ""
    if cover_letter_path and os.path.exists(cover_letter_path):
        with open(cover_letter_path) as f:
            lines = [l for l in f.read().split('\n')
                     if not l.startswith('#') and not l.startswith('**')]
            cover_letter_text = '\n'.join(lines).strip()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        print(f"Loading: {apply_url}")
        page.goto(apply_url, timeout=30000)
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        print(f"Title: {page.title()}")

        # ── fill standard Lever fields ─────────────────────────────────────
        def fill(name, value):
            try:
                loc = page.locator(f"input[name='{name}'], textarea[name='{name}']").first
                loc.wait_for(state="visible", timeout=3000)
                loc.fill(value)
                print(f"  {name}: OK")
                return True
            except Exception:
                return False

        fill("first_name",     APPLICANT["first_name"])
        fill("last_name",      APPLICANT["last_name"])
        fill("email",          APPLICANT["email"])
        fill("phone",          APPLICANT["phone"])
        fill("country",        APPLICANT["country"])
        fill("linkedin",       APPLICANT["linkedin"])
        fill("website",        APPLICANT["linkedin"])  # some forms use website

        # Cover letter text field (name varies)
        for cl_name in ["cover_letter", "comments", "message", "motivation"]:
            if cover_letter_text and fill(cl_name, cover_letter_text):
                break

        # Sponsorship field if present
        fill("sponsorship", APPLICANT["sponsorship"])

        # Leave honeypot field empty (hp_field / beecatcher / website — the trap)
        try:
            page.locator("input[name='hp_field']").fill("")
        except Exception:
            pass

        # Explicitly blank out salary and current-employer fields — never disclose
        for sensitive_name in ["salary", "current_salary", "desired_salary", "expected_salary",
                               "compensation", "current_company", "current_employer",
                               "current_title", "current_position", "current_role"]:
            try:
                page.locator(f"input[name='{sensitive_name}'], input[placeholder*='{sensitive_name}' i]").fill("")
            except Exception:
                pass

        # Resume file upload
        try:
            page.set_input_files("input[name='resume']", RESUME_PATH)
            print(f"  resume: OK ({os.path.basename(RESUME_PATH)})")
        except Exception as e:
            print(f"  resume upload issue: {e}")

        # ── any additional custom questions ──────────────────────────────
        # Check for extra text inputs not yet filled
        extra = page.locator("input[type='text']:not([name='first_name']):not([name='last_name']):not([name='country']):not([name='linkedin']):not([name='website']):not([name='sponsorship']):not([name='hp_field']), textarea:not([name='cover_letter']):not([name='comments']):not([name='motivation'])").all()
        if extra:
            print(f"  {len(extra)} additional fields detected — review in browser")

        # ── submit ────────────────────────────────────────────────────────
        print("\n✅ All standard fields filled. Submitting in 5 seconds... (close browser to cancel)")
        time.sleep(5)

        submitted = False
        for selector in ["button[type='submit']", "input[type='submit']",
                         "button:has-text('Submit')", "button:has-text('Apply')"]:
            try:
                page.locator(selector).first.click()
                submitted = True
                print("  Clicked submit")
                break
            except Exception:
                pass

        if submitted:
            time.sleep(4)
            content = page.content().lower()
            if any(w in content for w in ["thank you", "received", "submitted", "success", "application sent"]):
                print("✅ Application submitted successfully!")
            else:
                print("⚠️  Check browser for confirmation.")
                time.sleep(20)
        else:
            print("⚠️  Submit button not found — review and submit manually.")
            time.sleep(30)

        browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 apply_lever.py <apply_url> <cover_letter_path>")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])
