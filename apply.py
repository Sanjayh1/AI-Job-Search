"""
Job Application Automation Engine
Handles: LinkedIn Easy Apply, Teamtailor, Greenhouse, Lever, Workday, generic forms
Usage: python3 apply.py --url <job_url> --cover-letter <path_to_cover_letter>
       python3 apply.py --all-priority   (apply to all Priority jobs in tracker)
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
TRACKER_FILE = BASE_DIR / "tracker.csv"
COVER_LETTERS_DIR = BASE_DIR / "cover_letters"
RESUME_PATH = None  # Set from config

def save_cover_letter_as_txt(cover_letter_path: str):
    """Save cover letter markdown as a plain .txt file for upload. Returns path or None."""
    if not cover_letter_path:
        return None
    candidates = [
        Path(cover_letter_path),
        COVER_LETTERS_DIR / cover_letter_path,
        COVER_LETTERS_DIR / Path(cover_letter_path).name,
    ]
    md_path = None
    for p in candidates:
        if p.exists():
            md_path = p
            break
    if not md_path:
        return None
    txt_path = md_path.with_suffix(".txt")
    text = read_cover_letter_text(cover_letter_path)
    if text:
        txt_path.write_text(text)
        return str(txt_path)
    return None

def load_config():
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    global RESUME_PATH
    RESUME_PATH = config["candidate"]["resume_path"]
    return config

def read_tracker():
    rows = []
    with open(TRACKER_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def update_tracker_status(job_id, status, date_applied=None, notes_append=None):
    rows = read_tracker()
    fieldnames = list(rows[0].keys()) if rows else []
    for row in rows:
        if row["job_id"] == job_id:
            row["status"] = status
            if date_applied:
                row["date_applied"] = date_applied
            if notes_append:
                row["notes"] = (row.get("notes", "") + " | " + notes_append).strip(" |")
    with open(TRACKER_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def detect_ats(url: str) -> str:
    """Detect which ATS system the URL belongs to."""
    url_lower = url.lower()
    if "linkedin.com" in url_lower:
        return "linkedin"
    if "teamtailor.com" in url_lower:
        return "teamtailor"
    if "greenhouse.io" in url_lower or "boards.greenhouse" in url_lower:
        return "greenhouse"
    if "lever.co" in url_lower:
        return "lever"
    if "workday.com" in url_lower or "myworkdayjobs.com" in url_lower:
        return "workday"
    if "smartrecruiters.com" in url_lower:
        return "smartrecruiters"
    if "icims.com" in url_lower:
        return "icims"
    if "ashbyhq.com" in url_lower:
        return "ashby"
    return "generic"

def read_cover_letter_text(cover_letter_path: str) -> str:
    """Extract plain text from a cover letter markdown file."""
    if not cover_letter_path:
        return ""
    # Try multiple path resolutions
    candidates = [
        Path(cover_letter_path),
        COVER_LETTERS_DIR / cover_letter_path,
        COVER_LETTERS_DIR / Path(cover_letter_path).name,
        BASE_DIR / cover_letter_path,
    ]
    full_path = None
    for p in candidates:
        if p.exists():
            full_path = p
            break
    if not full_path:
        return ""
    text = full_path.read_text()
    # Strip markdown headers and meta section, return just the letter body
    lines = text.split("\n")
    letter_lines = []
    in_letter = False
    for line in lines:
        if line.startswith("---") and not in_letter:
            in_letter = True
            continue
        if in_letter and line.startswith("---"):
            break
        if in_letter:
            letter_lines.append(line)
    return "\n".join(letter_lines).strip()

def fill_common_fields(page: Page, config: dict, cover_letter_text: str):
    """Fill common form fields found across most ATS platforms."""
    candidate = config["candidate"]

    field_map = {
        # Name fields
        "first.name|firstname|first_name": candidate["name"].split()[0],
        "last.name|lastname|last_name": candidate["name"].split()[-1],
        "full.name|fullname|full_name|your.name": candidate["name"],
        # Contact
        "email": candidate["email"],
        "phone|mobile|telephone": candidate["phone"],
        # Location
        "location|city|address": candidate["location"],
        # LinkedIn
        "linkedin": candidate["linkedin"],
        # Cover letter
        "cover.letter|coverletter|cover_letter|motivation|message": cover_letter_text,
    }

    for selector_group, value in field_map.items():
        if not value:
            continue
        selectors = selector_group.split("|")
        for sel in selectors:
            patterns = [
                f'input[name*="{sel}"]',
                f'input[id*="{sel}"]',
                f'input[placeholder*="{sel}" i]',
                f'textarea[name*="{sel}"]',
                f'textarea[id*="{sel}"]',
                f'textarea[placeholder*="{sel}" i]',
            ]
            for pattern in patterns:
                try:
                    el = page.locator(pattern).first
                    if el.count() > 0 and el.is_visible():
                        el.fill(value)
                        break
                except Exception:
                    continue

def upload_resume(page: Page):
    """Find a file upload input and upload the resume."""
    upload_selectors = [
        'input[type="file"][accept*="pdf"]',
        'input[type="file"][name*="resume"]',
        'input[type="file"][name*="cv"]',
        'input[type="file"][id*="resume"]',
        'input[type="file"][id*="cv"]',
        'input[type="file"]',
    ]
    for selector in upload_selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                el.set_input_files(RESUME_PATH)
                print(f"  ✓ Resume uploaded via {selector}")
                return True
        except Exception:
            continue
    print("  ⚠ Could not find file upload field automatically")
    return False

def upload_cover_letter(page: Page, cover_letter_txt_path: str) -> bool:
    """Upload cover letter as a .txt file to any cover-letter-specific file input."""
    if not cover_letter_txt_path or not Path(cover_letter_txt_path).exists():
        return False
    selectors = [
        'input[type="file"][name*="cover"]',
        'input[type="file"][id*="cover"]',
        'input[type="file"][accept*="doc"]',
        'input[type="file"][name*="letter"]',
        'input[type="file"][id*="letter"]',
    ]
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                el.set_input_files(cover_letter_txt_path)
                print(f"  ✓ Cover letter uploaded via {selector}")
                return True
        except Exception:
            continue
    return False

def fill_cover_letter_textarea(page: Page, cover_letter_text: str) -> bool:
    """Fill cover letter into any textarea that looks like a cover letter or message field."""
    if not cover_letter_text:
        return False
    # Try specific cover-letter-labeled textareas first
    specific_selectors = [
        'textarea[name*="cover"]', 'textarea[id*="cover"]',
        'textarea[name*="letter"]', 'textarea[id*="letter"]',
        'textarea[name*="message"]', 'textarea[id*="message"]',
        'textarea[placeholder*="cover" i]', 'textarea[placeholder*="letter" i]',
        'textarea[aria-label*="cover" i]', 'textarea[aria-label*="letter" i]',
    ]
    for selector in specific_selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0 and el.is_visible():
                el.fill(cover_letter_text)
                print(f"  ✓ Cover letter filled in {selector}")
                return True
        except Exception:
            continue
    # Fallback: first empty visible textarea (likely a cover letter field)
    try:
        textareas = page.locator("textarea").all()
        for ta in textareas:
            if ta.is_visible():
                val = ta.input_value()
                if val == "" or len(val) < 20:
                    ta.fill(cover_letter_text)
                    print("  ✓ Cover letter filled in generic textarea")
                    return True
    except Exception:
        pass
    print("  ⚠ No cover letter textarea found")
    return False

def answer_yes_no_questions(page: Page):
    """Answer Yes/No qualifying questions — default to Yes for experience questions."""
    try:
        yes_radios = page.locator('input[type="radio"]').all()
        for radio in yes_radios:
            try:
                label = radio.get_attribute("value") or ""
                aria = radio.get_attribute("aria-label") or ""
                if "yes" in label.lower() or "yes" in aria.lower():
                    if not radio.is_checked():
                        radio.click()
            except Exception:
                pass
        yes_labels = page.get_by_text("Yes", exact=True).all()
        for label in yes_labels:
            try:
                label.click()
            except Exception:
                pass
    except Exception:
        pass

def fill_eeoc_fields(page: Page, config: dict):
    """Fill EEOC / demographic fields common on US job applications."""
    candidate = config["candidate"]

    # Work authorization dropdowns and radio buttons
    auth_terms = ["us citizen", "citizen", "authorized", "yes"]
    for term in auth_terms:
        try:
            selects = page.locator("select").all()
            for sel in selects:
                sel_id = (sel.get_attribute("id") or "").lower()
                sel_name = (sel.get_attribute("name") or "").lower()
                if any(w in sel_id + sel_name for w in ["auth", "visa", "sponsor", "citizen", "work_status"]):
                    options = sel.locator("option").all()
                    for opt in options:
                        opt_text = (opt.text_content() or "").lower()
                        if "citizen" in opt_text or "authorized" in opt_text or "yes" in opt_text:
                            sel.select_option(label=opt.text_content())
                            break
        except Exception:
            pass

    # Gender select/radio
    try:
        selects = page.locator("select").all()
        for sel in selects:
            sel_id = (sel.get_attribute("id") or "").lower()
            sel_name = (sel.get_attribute("name") or "").lower()
            if "gender" in sel_id + sel_name or "sex" in sel_id + sel_name:
                options = sel.locator("option").all()
                for opt in options:
                    if "male" in (opt.text_content() or "").lower() and "fe" not in (opt.text_content() or "").lower():
                        sel.select_option(label=opt.text_content())
                        break
    except Exception:
        pass

    # Ethnicity/Race select
    try:
        selects = page.locator("select").all()
        for sel in selects:
            sel_id = (sel.get_attribute("id") or "").lower()
            sel_name = (sel.get_attribute("name") or "").lower()
            if any(w in sel_id + sel_name for w in ["ethnic", "race", "racial"]):
                options = sel.locator("option").all()
                for opt in options:
                    if "asian" in (opt.text_content() or "").lower():
                        sel.select_option(label=opt.text_content())
                        break
    except Exception:
        pass

    # Veteran status — select "Not a veteran" / "I am not a protected veteran"
    try:
        selects = page.locator("select").all()
        for sel in selects:
            sel_id = (sel.get_attribute("id") or "").lower()
            sel_name = (sel.get_attribute("name") or "").lower()
            if "veteran" in sel_id + sel_name or "vet" in sel_id + sel_name:
                options = sel.locator("option").all()
                for opt in options:
                    opt_text = (opt.text_content() or "").lower()
                    if "not" in opt_text or "decline" in opt_text or "no" in opt_text:
                        sel.select_option(label=opt.text_content())
                        break
    except Exception:
        pass

    # Disability — select "No" / "I don't have a disability"
    try:
        selects = page.locator("select").all()
        for sel in selects:
            sel_id = (sel.get_attribute("id") or "").lower()
            sel_name = (sel.get_attribute("name") or "").lower()
            if "disab" in sel_id + sel_name:
                options = sel.locator("option").all()
                for opt in options:
                    opt_text = (opt.text_content() or "").lower()
                    if "not" in opt_text or "no " in opt_text or "decline" in opt_text:
                        sel.select_option(label=opt.text_content())
                        break
    except Exception:
        pass

    # Sponsorship radio — No
    try:
        radios = page.locator('input[type="radio"]').all()
        for radio in radios:
            name = (radio.get_attribute("name") or "").lower()
            value = (radio.get_attribute("value") or "").lower()
            if "sponsor" in name and ("no" in value or "false" in value or "0" == value):
                if not radio.is_checked():
                    radio.click()
    except Exception:
        pass

def apply_teamtailor(page: Page, url: str, config: dict, cover_letter_text: str, cover_letter_txt_path: str = "") -> bool:
    """Handle Teamtailor ATS applications."""
    print(f"  Navigating to Teamtailor form: {url}")
    page.goto(url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    # Click Apply button if present
    for btn_text in ["Apply for this job", "Apply now", "Apply"]:
        try:
            btn = page.get_by_role("button", name=btn_text).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                time.sleep(1)
                break
        except Exception:
            pass

    # Answer Yes/No qualifying questions
    answer_yes_no_questions(page)

    # Fill standard fields
    fill_common_fields(page, config, cover_letter_text)

    # Fill EEOC / demographic fields
    fill_eeoc_fields(page, config)

    # Upload resume
    upload_resume(page)

    # Upload cover letter as file and/or fill textarea
    upload_cover_letter(page, cover_letter_txt_path or "")
    fill_cover_letter_textarea(page, cover_letter_text)

    # Scroll to bottom to make sure all fields are visible
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)

    # Take screenshot before submitting
    screenshot_path = str(BASE_DIR / "screenshots" / f"teamtailor_preflight_{int(time.time())}.png")
    os.makedirs(BASE_DIR / "screenshots", exist_ok=True)
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"  📸 Pre-submit screenshot: {screenshot_path}")

    # Find and click the Submit button
    submitted = False
    for btn_text in ["Send application", "Submit application", "Submit", "Apply", "Send"]:
        try:
            btn = page.get_by_role("button", name=btn_text).first
            if btn.count() > 0 and btn.is_visible():
                print(f"  → Clicking '{btn_text}' button...")
                btn.click()
                time.sleep(3)
                submitted = True
                break
        except Exception:
            pass

    if not submitted:
        # Try input[type=submit]
        try:
            submit_input = page.locator('input[type="submit"], button[type="submit"]').first
            if submit_input.count() > 0:
                print("  → Clicking submit input...")
                submit_input.click()
                time.sleep(3)
                submitted = True
        except Exception:
            pass

    # Screenshot after submit
    post_path = str(BASE_DIR / "screenshots" / f"teamtailor_result_{int(time.time())}.png")
    page.screenshot(path=post_path, full_page=True)
    print(f"  📸 Post-submit screenshot: {post_path}")

    if submitted:
        print("  ✅ Submit clicked successfully")
    else:
        print("  ⚠ Could not find submit button — check post-submit screenshot")

    return submitted

def apply_greenhouse(page: Page, url: str, config: dict, cover_letter_text: str, cover_letter_txt_path: str = "") -> bool:
    """Handle Greenhouse ATS applications."""
    print(f"  Navigating to Greenhouse form: {url}")
    page.goto(url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    candidate = config["candidate"]

    for field_id, value in [
        ("first_name", candidate["name"].split()[0]),
        ("last_name", candidate["name"].split()[-1]),
        ("email", candidate["email"]),
        ("phone", candidate["phone"]),
    ]:
        try:
            el = page.locator(f'#{field_id}, [name="{field_id}"]').first
            if el.count() > 0:
                el.fill(value)
        except Exception:
            pass

    # Country field — Greenhouse uses a React Select component (not a standard <select>).
    # Selector '.select__container:has(label[for="country"]) .select__control' matches exactly 1 element.
    # Type "United States" to filter options rather than using ArrowDown (which selects Afghanistan first).
    try:
        ctrl = page.locator('.select__container:has(label[for="country"]) .select__control').first
        if ctrl.count() > 0:
            ctrl.click()
            time.sleep(0.4)
            page.keyboard.type("United States")
            time.sleep(0.6)
            opt = page.get_by_role("option").filter(has_text="United States").nth(0)
            if opt.count() > 0 and opt.is_visible():
                opt.click()
            else:
                page.keyboard.press("Enter")
            time.sleep(0.3)
    except Exception:
        pass

    upload_resume(page)
    upload_cover_letter(page, cover_letter_txt_path)
    fill_cover_letter_textarea(page, cover_letter_text)
    fill_eeoc_fields(page, config)

    # Address fields (Greenhouse-specific custom questions vary by job; fill common patterns)
    addr = candidate.get("address", "")
    city = candidate.get("city", "")
    state = candidate.get("state", "")
    zip_code = candidate.get("zip", "")
    for pattern, value in [("street|address", addr), ("city", city), ("state|province", state), ("zip|postal", zip_code)]:
        if not value:
            continue
        for sel in pattern.split("|"):
            try:
                el = page.locator(f'input[id*="{sel}" i], input[name*="{sel}" i], input[placeholder*="{sel}" i]').first
                if el.count() > 0 and el.is_visible():
                    el.fill(value)
                    break
            except Exception:
                pass

    # Find and click Submit
    for btn_text in ["Submit Application", "Submit", "Apply"]:
        try:
            btn = page.get_by_role("button", name=btn_text).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                time.sleep(3)
                print(f"  ✅ Submitted via Greenhouse")
                break
        except Exception:
            pass

    screenshot_path = str(BASE_DIR / "screenshots" / f"greenhouse_{int(time.time())}.png")
    os.makedirs(BASE_DIR / "screenshots", exist_ok=True)
    page.screenshot(path=screenshot_path)
    print(f"  📸 Screenshot: {screenshot_path}")
    return True

def apply_lever(page: Page, url: str, config: dict, cover_letter_text: str, cover_letter_txt_path: str = "") -> bool:
    """Handle Lever ATS applications."""
    print(f"  Navigating to Lever form: {url}")
    page.goto(url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    candidate = config["candidate"]

    for placeholder, value in [
        ("Full name", candidate["name"]),
        ("Email", candidate["email"]),
        ("Phone", candidate["phone"]),
        ("LinkedIn Profile", candidate["linkedin"]),
    ]:
        try:
            el = page.get_by_placeholder(placeholder).first
            if el.count() > 0:
                el.fill(value)
        except Exception:
            pass

    upload_resume(page)
    upload_cover_letter(page, cover_letter_txt_path)
    fill_cover_letter_textarea(page, cover_letter_text)
    fill_eeoc_fields(page, config)

    # Submit
    try:
        btn = page.get_by_role("button", name="Submit application").first
        if btn.count() > 0:
            btn.click()
            time.sleep(3)
            print("  ✅ Submitted via Lever")
    except Exception:
        pass

    screenshot_path = str(BASE_DIR / "screenshots" / f"lever_{int(time.time())}.png")
    os.makedirs(BASE_DIR / "screenshots", exist_ok=True)
    page.screenshot(path=screenshot_path)
    print(f"  📸 Screenshot: {screenshot_path}")
    return True

def apply_linkedin_easy_apply(page: Page, url: str, config: dict, cover_letter_text: str, cover_letter_txt_path: str = "") -> bool:
    """Handle LinkedIn jobs — Easy Apply modal OR redirect to external ATS."""
    print(f"  Opening LinkedIn job: {url}")
    page.goto(url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    # --- Check for Easy Apply first ---
    easy_apply_btn = None
    try:
        btn = page.get_by_role("button", name="Easy Apply").first
        if btn.count() > 0 and btn.is_visible():
            easy_apply_btn = btn
    except Exception:
        pass

    if easy_apply_btn:
        print("  → Easy Apply detected")
        easy_apply_btn.click()
        time.sleep(2)

        # Multi-step modal
        max_steps = 12
        for step in range(max_steps):
            time.sleep(1.5)
            fill_common_fields(page, config, cover_letter_text)
            upload_resume(page)
            upload_cover_letter(page, cover_letter_txt_path)
            fill_cover_letter_textarea(page, cover_letter_text)
            fill_eeoc_fields(page, config)
            answer_yes_no_questions(page)

            advanced = False
            for btn_text in ["Submit application", "Review", "Next"]:
                try:
                    btn = page.get_by_role("button", name=btn_text).first
                    if btn.count() > 0 and btn.is_visible():
                        if btn_text == "Submit application":
                            btn.click()
                            time.sleep(2)
                            print("  ✅ Submitted via LinkedIn Easy Apply")
                            return True
                        btn.click()
                        advanced = True
                        break
                except Exception:
                    pass

            if not advanced:
                break

        print("  ⚠ Easy Apply flow did not reach Submit")
        return False

    # --- No Easy Apply — check for "Apply on company website" link ---
    external_url = None
    try:
        # Try to get the href from the Apply link
        apply_link = page.locator('a[href*="apply"], a:has-text("Apply on company website")').first
        if apply_link.count() > 0:
            href = apply_link.get_attribute("href") or ""
            # LinkedIn wraps external URLs in a safety redirect — extract real URL
            if "linkedin.com/safety/go" in href:
                import urllib.parse
                parsed = urllib.parse.urlparse(href)
                params = urllib.parse.parse_qs(parsed.query)
                external_url = urllib.parse.unquote(params.get("url", [""])[0])
            elif href.startswith("http") and "linkedin.com" not in href:
                external_url = href
    except Exception:
        pass

    if external_url:
        print(f"  → External ATS detected: {external_url}")
        ats = detect_ats(external_url)
        print(f"  → ATS type: {ats.upper()}")
        if ats == "teamtailor":
            return apply_teamtailor(page, external_url, config, cover_letter_text, cover_letter_txt_path)
        elif ats == "greenhouse":
            return apply_greenhouse(page, external_url, config, cover_letter_text, cover_letter_txt_path)
        elif ats == "lever":
            return apply_lever(page, external_url, config, cover_letter_text, cover_letter_txt_path)
        elif ats == "ashby":
            return apply_ashby(page, external_url, config, cover_letter_text, cover_letter_txt_path)
        else:
            return apply_generic(page, external_url, config, cover_letter_text, cover_letter_txt_path)

    print("  ⚠ No Easy Apply or external apply link found — may require LinkedIn login")
    return False

def apply_ashby(page: Page, url: str, config: dict, cover_letter_text: str, cover_letter_txt_path: str = "") -> bool:
    """Handle Ashby HQ ATS applications."""
    print(f"  Navigating to Ashby form: {url}")
    page.goto(url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    candidate = config["candidate"]
    profile = config.get("profile_summary", {})
    current_company = profile.get("current_company", "")
    current_title = profile.get("current_title", "")

    # Click "Apply" button if on the job description page
    for btn_text in ["Apply", "Apply Now", "Apply for this job"]:
        try:
            btn = page.get_by_role("button", name=btn_text).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                time.sleep(1.5)
                break
        except Exception:
            pass

    # --- System fields (stable IDs across all Ashby forms) ---
    for field_id, value in [
        ("_systemfield_name", candidate["name"]),
        ("_systemfield_email", candidate["email"]),
    ]:
        try:
            el = page.locator(f"#{field_id}").first
            if el.count() > 0 and el.is_visible():
                el.fill(value)
                time.sleep(0.2)
        except Exception:
            pass

    # --- Custom labeled fields — short substrings survive "/" and "*" in label text ---
    # Ashby labels: "Current/Most Recent Company Name", "Current/Most Recent Job Title"
    for label_substr, value in [
        ("LinkedIn Profile", candidate["linkedin"]),
        ("Phone Number", candidate["phone"]),
        ("Company Name", current_company),   # matches "Current/Most Recent Company Name"
        ("Job Title", current_title),         # matches "Current/Most Recent Job Title"
        ("pronouns", "He/Him"),               # matches "What are your pronouns? (Optional)"
    ]:
        if not value:
            continue
        try:
            el = page.get_by_label(label_substr, exact=False).first
            if el.count() > 0 and el.is_visible():
                el.fill(value)
                time.sleep(0.2)
        except Exception:
            pass

    # --- Location autocomplete (Ashby: wrapper div #_systemfield_location, inner input has placeholder "Start typing...") ---
    # The label for="_systemfield_location" points to the wrapper div, not the input.
    # Must find the actual <input> by placeholder or by searching inside the wrapper.
    loc_query = f"{candidate.get('city', '')}, {candidate.get('state', '')}"
    try:
        # Try inner input first, then fall back to placeholder search
        loc_input = page.locator("#_systemfield_location input").first
        if loc_input.count() == 0 or not loc_input.is_visible():
            loc_input = page.get_by_placeholder("Start typing...").first
        if loc_input.count() > 0 and loc_input.is_visible():
            loc_input.click()
            time.sleep(0.5)
            page.keyboard.type(loc_query, delay=80)
            time.sleep(2.5)
            # Click first autocomplete suggestion
            option = page.locator('[role="option"]').first
            if option.count() > 0 and option.is_visible():
                option.click()
            else:
                page.keyboard.press("ArrowDown")
                time.sleep(0.4)
                page.keyboard.press("Enter")
            time.sleep(0.5)
    except Exception:
        pass

    # --- Ashby Yes/No questions ---
    # Ashby renders these as <button class="...option...">Yes</button> / No buttons.
    # Order on form: [Yes(auth), No(auth), Yes(sponsor), No(sponsor)]
    # We want: Yes for authorization (index 0), No for sponsorship (index 3 / last No)
    try:
        yes_btns = page.get_by_role("button", name="Yes").all()
        no_btns  = page.get_by_role("button", name="No").all()
        print(f"  Yes buttons: {len(yes_btns)}, No buttons: {len(no_btns)}")
        if yes_btns:
            yes_btns[0].click()   # Authorization: Yes
            time.sleep(0.3)
        if len(no_btns) >= 2:
            no_btns[-1].click()   # Sponsorship: No (last No button)
            time.sleep(0.3)
        elif len(no_btns) == 1:
            no_btns[0].click()
            time.sleep(0.3)
    except Exception as e:
        print(f"  ⚠ Yes/No click error: {e}")

    # --- SMS consent: select "No - I do not consent" radio ---
    try:
        no_sms = page.get_by_label("No - I do not consent", exact=False).first
        if no_sms.count() > 0:
            no_sms.click(force=True)
            time.sleep(0.2)
    except Exception:
        pass

    # --- Upload resume and cover letter ---
    upload_resume(page)
    upload_cover_letter(page, cover_letter_txt_path)
    fill_cover_letter_textarea(page, cover_letter_text)

    # --- EEOC radio buttons (Ashby uses radios, not selects) ---
    for radio_label in ["Male", "Asian (Not Hispanic or Latino)", "I am not a protected veteran"]:
        try:
            radio = page.get_by_label(radio_label, exact=True).first
            if radio.count() > 0 and radio.is_visible() and not radio.is_checked():
                radio.click()
                time.sleep(0.2)
        except Exception:
            pass

    # Screenshot before submit
    screenshot_path = str(BASE_DIR / "screenshots" / f"ashby_preflight_{int(time.time())}.png")
    os.makedirs(BASE_DIR / "screenshots", exist_ok=True)
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"  📸 Pre-submit screenshot: {screenshot_path}")

    # Find and click Submit
    submitted = False
    for btn_text in ["Submit Application", "Submit application", "Submit", "Apply"]:
        try:
            btn = page.get_by_role("button", name=btn_text).first
            if btn.count() > 0 and btn.is_visible():
                print(f"  → Clicking '{btn_text}'...")
                btn.click()
                time.sleep(3)
                submitted = True
                break
        except Exception:
            pass

    if not submitted:
        try:
            submit_input = page.locator('button[type="submit"], input[type="submit"]').first
            if submit_input.count() > 0:
                submit_input.click()
                time.sleep(3)
                submitted = True
        except Exception:
            pass

    # Wait for page to settle after submit
    time.sleep(8)
    post_path = str(BASE_DIR / "screenshots" / f"ashby_result_{int(time.time())}.png")
    page.screenshot(path=post_path, full_page=True)
    print(f"  📸 Post-submit screenshot: {post_path}")
    print(f"  URL after submit: {page.url}")

    # Check for success vs. failure — get full page text
    page_text = page.evaluate("document.body.innerText") or ""
    success_phrases = ["thank you", "application submitted", "application received", "we'll be in touch", "application complete", "your application has been", "successfully submitted", "we'll contact you"]
    error_phrases = ["required field", "please fill", "verification failed", "captcha", "field is required"]

    found_success = any(p in page_text.lower() for p in success_phrases)
    found_error = any(p in page_text.lower() for p in error_phrases)

    print(f"  Page text (first 600): {page_text[:600]}")

    if found_success:
        print(f"  ✅ SUCCESS: confirmation text found on page")
        return True
    elif found_error:
        for phrase in error_phrases:
            idx = page_text.lower().find(phrase)
            if idx >= 0:
                snippet = page_text[max(0,idx-50):idx+200].strip()
                print(f"  ⚠ ERROR '{phrase}': ...{snippet}...")
                break
        print(f"  ⚠ Form validation error — check post-submit screenshot")
        return False
    elif submitted:
        if "applied" in page.url.lower() or "confirmation" in page.url.lower() or "thank" in page.url.lower():
            print(f"  ✅ SUCCESS: URL indicates completion")
            return True
        print(f"  ⚠ Form status unclear — manual verification recommended")
        return True
    else:
        print("  ⚠ Submit not found — check post-submit screenshot")
        return False


def apply_generic(page: Page, url: str, config: dict, cover_letter_text: str, cover_letter_txt_path: str = "") -> bool:
    """Fallback: navigate, fill common fields, screenshot for review."""
    print(f"  Navigating to form (generic): {url}")
    page.goto(url, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    fill_common_fields(page, config, cover_letter_text)
    upload_resume(page)
    upload_cover_letter(page, cover_letter_txt_path)
    fill_cover_letter_textarea(page, cover_letter_text)
    fill_eeoc_fields(page, config)

    screenshot_path = str(BASE_DIR / "screenshots" / f"generic_{int(time.time())}.png")
    os.makedirs(BASE_DIR / "screenshots", exist_ok=True)
    page.screenshot(path=screenshot_path)
    print(f"  📸 Screenshot saved: {screenshot_path}")
    return True

def apply_to_job(url: str, cover_letter_path: str, config: dict, headless: bool = False) -> bool:
    """Main application function — detects ATS, generates cover letter txt, applies."""
    ats = detect_ats(url)
    cover_letter_text = read_cover_letter_text(cover_letter_path)
    cover_letter_txt_path = save_cover_letter_as_txt(cover_letter_path) or ""

    print(f"\n{'='*60}")
    print(f"Applying to: {url}")
    print(f"ATS detected: {ats.upper()}")
    print(f"Resume: {RESUME_PATH}")
    print(f"Cover letter text: {'loaded ✓' if cover_letter_text else 'none'}")
    print(f"Cover letter file: {cover_letter_txt_path or 'none'}")
    print(f"{'='*60}")

    with sync_playwright() as p:
        # Try system Chrome first (better reCAPTCHA score), fall back to bundled Chromium
        try:
            browser = p.chromium.launch(headless=headless, channel="chrome", slow_mo=300)
        except Exception:
            browser = p.chromium.launch(headless=headless, slow_mo=300)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            success = False
            if ats == "linkedin":
                success = apply_linkedin_easy_apply(page, url, config, cover_letter_text, cover_letter_txt_path)
            elif ats == "teamtailor":
                success = apply_teamtailor(page, url, config, cover_letter_text, cover_letter_txt_path)
            elif ats == "greenhouse":
                success = apply_greenhouse(page, url, config, cover_letter_text, cover_letter_txt_path)
            elif ats == "lever":
                success = apply_lever(page, url, config, cover_letter_text, cover_letter_txt_path)
            elif ats == "ashby":
                success = apply_ashby(page, url, config, cover_letter_text, cover_letter_txt_path)
            else:
                success = apply_generic(page, url, config, cover_letter_text, cover_letter_txt_path)

            return success
        except PlaywrightTimeout:
            print(f"  ⚠ Page timed out loading: {url}")
            return False
        except Exception as e:
            print(f"  ✗ Error during application: {e}")
            return False
        finally:
            browser.close()

def apply_all_priority():
    """Apply to all jobs in tracker with status 'Priority'."""
    config = load_config()
    rows = read_tracker()
    priority_jobs = [r for r in rows if r.get("status") == "Priority" and not r.get("date_applied")]

    if not priority_jobs:
        print("No Priority jobs without a date_applied found in tracker.")
        return

    print(f"Found {len(priority_jobs)} Priority job(s) to apply to.")

    for job in priority_jobs:
        job_id = job["job_id"]
        title = job["title"]
        company = job["company"]
        apply_url = job["apply_url"]
        cover_letter = job.get("cover_letter_file", "")

        print(f"\n→ Applying: {title} at {company}")

        success = apply_to_job(apply_url, cover_letter, config, headless=False)

        if success:
            update_tracker_status(job_id, "Applied", date_applied=str(date.today()))
            print(f"  ✅ Tracker updated: Applied on {date.today()}")
        else:
            update_tracker_status(job_id, "Priority", notes_append="Auto-apply attempted but needs manual review")
            print(f"  ⚠ Manual review needed — check screenshot in job_hunter/screenshots/")

def main():
    parser = argparse.ArgumentParser(description="Automated job application engine")
    parser.add_argument("--url", help="Job application URL")
    parser.add_argument("--cover-letter", help="Path to cover letter file", default="")
    parser.add_argument("--all-priority", action="store_true", help="Apply to all Priority jobs in tracker")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    args = parser.parse_args()

    config = load_config()

    if args.all_priority:
        apply_all_priority()
    elif args.url:
        success = apply_to_job(args.url, args.cover_letter, config, headless=args.headless)
        if success:
            print("\n✅ Application process completed.")
        else:
            print("\n⚠ Application needs manual review. Check screenshots folder.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
