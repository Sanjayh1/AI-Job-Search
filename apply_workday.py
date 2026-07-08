"""
Automated Workday job application.
Usage: python3 apply_workday.py <job_details_url> <cover_letter_path>

The script:
  - Navigates to the job and clicks Apply → Autofill with Resume
  - Pre-fills the email in the Create Account form, then PAUSES
  - You enter your password + click Create Account (15-second window per attempt)
  - Script handles ALL remaining steps: resume upload, My Information,
    My Experience, Application Questions, Voluntary Disclosures, Review, Submit
"""

import sys
import time
import os
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

CONFIG_FILE = Path(__file__).parent / "config.json"
with open(CONFIG_FILE) as f:
    _candidate = json.load(f)["candidate"]

RESUME_PATH = _candidate["resume_path"]
_name_parts = _candidate["name"].split()

APPLICANT = {
    "email":      _candidate["email"],
    "first_name": _name_parts[0],
    "last_name":  _name_parts[-1],
    "phone":      _candidate["phone"],
    "address1":   _candidate["address"],
    "city":       _candidate["city"],
    "state":      _candidate["state"],
    "zip":        _candidate["zip"],
    "country":    "United States of America",
    "linkedin":   _candidate["linkedin"],
}


# ── helpers ────────────────────────────────────────────────────────────────

def fill_by_aid(page, aid, value, timeout=5000):
    try:
        loc = page.locator(f"[data-automation-id='{aid}']").first
        loc.wait_for(state="visible", timeout=timeout)
        loc.fill(value)
        return True
    except Exception:
        return False


def fill_by_label(page, label_text, value, exact=False):
    try:
        page.get_by_label(label_text, exact=exact).first.fill(value)
        return True
    except Exception:
        return False


def click_by_aid(page, aid, timeout=8000):
    try:
        loc = page.locator(f"[data-automation-id='{aid}']").first
        loc.wait_for(state="visible", timeout=timeout)
        loc.click()
        return True
    except Exception:
        return False


def wait_for_step(page, step_keyword, max_wait=120):
    """Wait until the page title or URL contains step_keyword."""
    print(f"  Waiting for step: {step_keyword} (up to {max_wait}s)...")
    for _ in range(max_wait):
        title = page.title().lower()
        url = page.url.lower()
        text = page.inner_text("body").lower()[:300]
        if step_keyword.lower() in title + url + text:
            return True
        time.sleep(1)
    return False


def current_step(page):
    try:
        return page.inner_text("[data-automation-id='currentStep'], [aria-current='step'], .css-currentStep").strip()
    except Exception:
        pass
    try:
        return page.title().strip()
    except Exception:
        return "unknown"


def click_next_or_save(page):
    """Click the Next / Save and Continue button to advance the form."""
    for aid in ["bottom-navigation-next-btn", "bottomNavigationNextBtn",
                "wd-CommandButton-nextButton", "nextButton"]:
        if click_by_aid(page, aid, timeout=3000):
            time.sleep(2)
            return True
    # Fallback: button text
    for label in ["Next", "Save and Continue", "Continue", "Save"]:
        try:
            page.locator(f"button:has-text('{label}')").first.click()
            time.sleep(2)
            return True
        except Exception:
            pass
    return False


# ── step handlers ──────────────────────────────────────────────────────────

def step_create_account(page):
    """Fill email, then pause so user can enter password."""
    print("\n[Step 1: Create Account]")
    fill_by_aid(page, "email", APPLICANT["email"])
    print(f"  Pre-filled email: {APPLICANT['email']}")
    print()
    print("  ⚠️  ACTION REQUIRED IN BROWSER:")
    print("      Enter your password, confirm it, check the terms box,")
    print("      then click 'Create Account'.")
    print("      Waiting up to 120 seconds...")
    # Wait until we leave the Create Account page (URL changes)
    start_url = page.url
    for _ in range(120):
        time.sleep(1)
        if page.url != start_url and "applyManually" not in page.url and "autofillWithResume" not in page.url:
            # Also check we're past step 1
            text = page.inner_text("body").lower()[:200]
            if "create account" not in text or "my information" in text or "autofill" in text:
                print("  Account created / signed in ✅")
                return True
        # Also accept if page moved to step 2
        if "step 2" in page.inner_text("body").lower()[:400]:
            print("  Moved to step 2 ✅")
            return True
    print("  ⚠️  Timeout waiting for account creation — attempting to continue anyway")
    return False


def step_autofill_resume(page):
    """Upload resume for Workday to parse and autofill work history."""
    print("\n[Step: Autofill with Resume]")
    time.sleep(2)
    # Look for file input
    file_input = page.locator("input[type='file']").first
    try:
        file_input.wait_for(state="attached", timeout=8000)
        file_input.set_input_files(RESUME_PATH)
        print(f"  Uploaded: {os.path.basename(RESUME_PATH)}")
        time.sleep(4)  # Wait for parsing
        # Click Continue/Next after upload
        click_next_or_save(page)
        time.sleep(3)
        return True
    except Exception as e:
        print(f"  File upload issue: {e}")
        click_next_or_save(page)
        return False


def step_my_information(page):
    """Fill contact info: name, phone, address."""
    print("\n[Step: My Information]")
    time.sleep(2)

    # Legal name
    fill_by_aid(page, "legalNameSection_firstName", APPLICANT["first_name"]) or \
        fill_by_label(page, "First Name", APPLICANT["first_name"])
    fill_by_aid(page, "legalNameSection_lastName", APPLICANT["last_name"]) or \
        fill_by_label(page, "Last Name", APPLICANT["last_name"])
    print(f"  Name: {APPLICANT['first_name']} {APPLICANT['last_name']}")

    # Phone — look for phone number field
    fill_by_aid(page, "phone-number", APPLICANT["phone"]) or \
        fill_by_label(page, "Phone Number", APPLICANT["phone"])
    print(f"  Phone: {APPLICANT['phone']}")

    # Address
    fill_by_aid(page, "addressSection_addressLine1", APPLICANT["address1"]) or \
        fill_by_label(page, "Address Line 1", APPLICANT["address1"])
    fill_by_aid(page, "addressSection_city", APPLICANT["city"]) or \
        fill_by_label(page, "City", APPLICANT["city"])
    print(f"  Address: {APPLICANT['address1']}, {APPLICANT['city']}")

    # Country/State selects (Workday uses typeahead selects)
    for country_aid in ["addressSection_countryRegion", "country"]:
        try:
            loc = page.locator(f"[data-automation-id='{country_aid}']").first
            loc.wait_for(state="visible", timeout=3000)
            loc.click()
            time.sleep(0.5)
            page.keyboard.type(APPLICANT["country"][:6])
            time.sleep(1)
            page.locator("[data-automation-id='promptOption']", has_text=APPLICANT["country"]).first.click()
            print(f"  Country: {APPLICANT['country']}")
            break
        except Exception:
            pass

    time.sleep(1)
    click_next_or_save(page)
    time.sleep(3)


def step_my_experience(page):
    """Resume already autofilled from step 2. Just upload cover letter and advance."""
    print("\n[Step: My Experience]")
    time.sleep(2)

    # Try to upload cover letter if a file input exists that isn't for resume
    file_inputs = page.locator("input[type='file']").all()
    for fi in file_inputs:
        label_id = fi.get_attribute("aria-labelledby") or ""
        nearby_text = ""
        try:
            nearby_text = fi.evaluate("el => el.closest('div')?.textContent || ''").lower()
        except Exception:
            pass
        if "cover" in nearby_text or "letter" in nearby_text:
            fi.set_input_files(RESUME_PATH)  # upload cover letter doc if available
            print("  Cover letter file field found — uploading")
            break

    click_next_or_save(page)
    time.sleep(3)


def step_application_questions(page, cover_letter_text="", extra_answers=None):
    """Answer free-text and yes/no application questions."""
    print("\n[Step: Application Questions]")
    time.sleep(2)
    extra_answers = extra_answers or {}

    # Look for text areas (usually a "cover letter" or open-ended question)
    text_areas = page.locator("textarea").all()
    for ta in text_areas:
        aid = ta.get_attribute("data-automation-id") or ""
        placeholder = (ta.get_attribute("placeholder") or "").lower()
        label_id = ta.get_attribute("aria-labelledby") or ""
        label_text = ""
        if label_id:
            try:
                label_text = page.locator(f"#{label_id}").inner_text().lower()
            except Exception:
                pass
        if cover_letter_text and ("cover" in label_text or "cover" in placeholder or "letter" in label_text):
            ta.fill(cover_letter_text)
            print("  Filled cover letter textarea")
        elif cover_letter_text and len(text_areas) == 1:
            ta.fill(cover_letter_text)
            print("  Filled single textarea with cover letter")

    # Answer extra questions by label — skip any salary/title fields
    SENSITIVE_KEYWORDS = {"salary", "compensation", "current salary", "desired salary",
                          "expected salary", "current title", "current position",
                          "current role", "current company", "current employer"}
    for question_label, answer in extra_answers.items():
        if any(kw in question_label.lower() for kw in SENSITIVE_KEYWORDS):
            print(f"  Skipped sensitive field: {question_label[:50]}")
            continue
        fill_by_label(page, question_label, str(answer)) or \
            fill_by_label(page, question_label, str(answer), exact=False)
        print(f"  Answered: {question_label[:50]} = {answer}")

    # Blank out any salary / current-employer inputs the form may have auto-surfaced
    for kw in ["salary", "compensation", "current_title", "current_company", "current_employer"]:
        for loc in page.locator(f"input[placeholder*='{kw}' i], input[aria-label*='{kw}' i]").all():
            try:
                loc.fill("")
            except Exception:
                pass

    click_next_or_save(page)
    time.sleep(3)


def step_voluntary_disclosures(page):
    """Decline/skip voluntary disclosure fields and advance."""
    print("\n[Step: Voluntary Disclosures]")
    time.sleep(2)
    # These are optional — just advance
    click_next_or_save(page)
    time.sleep(3)


def step_review_and_submit(page):
    """Review the application and submit."""
    print("\n[Step: Review & Submit]")
    time.sleep(2)

    print("  Submitting in 5 seconds... (close browser to cancel)")
    time.sleep(5)

    # Click Submit
    submitted = False
    for aid in ["submit-button", "wd-CommandButton-submitButton", "submitButton"]:
        if click_by_aid(page, aid, timeout=3000):
            submitted = True
            break
    if not submitted:
        for label in ["Submit", "Submit Application"]:
            try:
                page.locator(f"button:has-text('{label}')").first.click()
                submitted = True
                break
            except Exception:
                pass

    if submitted:
        time.sleep(4)
        content = page.content().lower()
        if any(w in content for w in ["thank you", "application received", "submitted", "successfully"]):
            print("  ✅ Application submitted successfully!")
        else:
            print("  ⚠️  Check browser — submission may need confirmation.")
            time.sleep(20)
    else:
        print("  ⚠️  Could not find Submit button. Review and submit manually.")
        time.sleep(30)


# ── main ───────────────────────────────────────────────────────────────────

def run(job_details_url, cover_letter_path, extra_answers=None):
    extra_answers = extra_answers or {}

    cover_letter_text = ""
    if cover_letter_path and os.path.exists(cover_letter_path):
        with open(cover_letter_path) as f:
            lines = [l for l in f.read().split('\n') if not l.startswith('#') and not l.startswith('**')]
            cover_letter_text = '\n'.join(lines).strip()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"\nLoading: {job_details_url}")
        page.goto(job_details_url)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # Click Apply (adventureButton)
        if not click_by_aid(page, "adventureButton"):
            print("⚠️  Apply button not found — check URL")
            browser.close()
            return

        time.sleep(2)

        # Prefer autofill path; fall back to manual
        if click_by_aid(page, "autofillWithResume", timeout=4000):
            print("Using: Autofill with Resume path")
            use_autofill = True
        elif click_by_aid(page, "applyManually", timeout=4000):
            print("Using: Apply Manually path")
            use_autofill = False
        else:
            print("⚠️  Neither autofill nor manual path found")
            browser.close()
            return

        page.wait_for_load_state("networkidle")
        time.sleep(2)

        # Step 1: Create Account (user must enter password)
        step_create_account(page)
        time.sleep(2)

        # Determine current step after account creation
        page_text = page.inner_text("body").lower()[:500]

        if use_autofill and ("autofill" in page_text or "upload" in page_text or "resume" in page_text and "upload" in page_text):
            step_autofill_resume(page)

        # Step: My Information
        if wait_for_step(page, "information", max_wait=10):
            step_my_information(page)

        # Step: My Experience
        if wait_for_step(page, "experience", max_wait=10):
            step_my_experience(page)

        # Step: Application Questions
        if wait_for_step(page, "question", max_wait=10):
            step_application_questions(page, cover_letter_text, extra_answers)

        # Step: Voluntary Disclosures
        if wait_for_step(page, "disclosure", max_wait=10):
            step_voluntary_disclosures(page)

        # Step: Review & Submit
        if wait_for_step(page, "review", max_wait=10):
            step_review_and_submit(page)
        else:
            # Try to submit whatever we're on
            print("\nAttempting final submission...")
            step_review_and_submit(page)

        browser.close()
        print("\nDone.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 apply_workday.py <job_details_url> <cover_letter_path>")
        print("Example:")
        print("  python3 apply_workday.py \\")
        print("    'https://temenos.wd103.myworkdayjobs.com/.../details/..._JR1861' \\")
        print("    'cover_letters/2026-06-10_Temenos_SrDir.md'")
        sys.exit(1)

    url = sys.argv[1]
    cl = sys.argv[2]
    answers = {}
    if len(sys.argv) > 3:
        import json
        answers = json.loads(sys.argv[3])
    run(url, cl, answers)
