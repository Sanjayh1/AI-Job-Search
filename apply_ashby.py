"""
Automated application for any Ashby-hosted job.
Usage: python3 apply_ashby.py <job_url> <cover_letter_path> [extra answers as JSON]
"""
import sys
import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

CONFIG_FILE = Path(__file__).parent / "config.json"
with open(CONFIG_FILE) as f:
    _candidate = json.load(f)["candidate"]

RESUME_PATH = _candidate["resume_path"]

APPLICANT = {
    "name": _candidate["name"],
    "email": _candidate["email"],
    "phone": _candidate["phone"],
    "linkedin": _candidate["linkedin"],
}

def fill_ashby_form(page, cover_letter_path, extra_answers=None):
    """Fill all standard Ashby application fields."""
    extra_answers = extra_answers or {}

    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Name
    name_field = page.locator("input[autocomplete='name'], input[placeholder*='name' i], input[aria-label*='name' i]").first
    try:
        name_field.wait_for(state="visible", timeout=5000)
        name_field.fill(APPLICANT["name"])
        print("  Filled: Name")
    except Exception:
        # Try by label text
        page.get_by_label("Name", exact=False).first.fill(APPLICANT["name"])
        print("  Filled: Name (by label)")

    # Email
    try:
        page.get_by_label("Email", exact=False).first.fill(APPLICANT["email"])
        print("  Filled: Email")
    except Exception:
        page.locator("input[type='email']").first.fill(APPLICANT["email"])

    # Phone
    try:
        page.get_by_label("Phone", exact=False).first.fill(APPLICANT["phone"])
        print("  Filled: Phone")
    except Exception:
        page.locator("input[type='tel']").first.fill(APPLICANT["phone"])

    # Resume upload
    try:
        resume_input = page.locator("input[type='file']").first
        resume_input.set_input_files(RESUME_PATH)
        print("  Uploaded: Resume")
        time.sleep(2)
    except Exception as e:
        print(f"  Resume upload issue: {e}")

    # LinkedIn
    try:
        linkedin_field = page.get_by_label("LinkedIn", exact=False).first
        linkedin_field.fill(APPLICANT["linkedin"])
        print("  Filled: LinkedIn")
    except Exception:
        pass

    # Extra answers — skip salary/title/company fields, never disclose
    SENSITIVE_KEYWORDS = {"salary", "compensation", "current title", "current position",
                          "current role", "current company", "current employer", "expected salary",
                          "desired salary", "current salary"}
    for label_text, answer in extra_answers.items():
        if any(kw in label_text.lower() for kw in SENSITIVE_KEYWORDS):
            print(f"  Skipped sensitive field: {label_text}")
            continue
        try:
            field = page.get_by_label(label_text, exact=False).first
            field_type = field.get_attribute("type") or ""
            if field_type == "checkbox":
                if answer:
                    field.check()
                else:
                    field.uncheck()
            else:
                field.fill(str(answer))
            print(f"  Filled: {label_text} = {answer}")
        except Exception as e:
            print(f"  Could not fill '{label_text}': {e}")

    # Handle boolean Yes/No fields via click on radio-style buttons
    for label_text, answer in extra_answers.items():
        if isinstance(answer, bool):
            try:
                btn_text = "Yes" if answer else "No"
                # Find the field group and click the right button
                label_el = page.get_by_text(label_text, exact=False).first
                group = label_el.locator("..").locator("..")
                group.get_by_text(btn_text, exact=True).click()
                print(f"  Selected: {label_text} → {btn_text}")
            except Exception:
                pass

def run(job_url, cover_letter_path, extra_answers=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        print(f"Loading: {job_url}")
        page.goto(job_url)
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # If we're on the job description page, click Apply
        apply_btn = page.locator("a:has-text('Apply'), button:has-text('Apply'), a:has-text('Apply now'), button:has-text('Apply now')").first
        try:
            apply_btn.wait_for(state="visible", timeout=3000)
            apply_btn.click()
            page.wait_for_load_state("networkidle")
            time.sleep(1)
            print("Clicked Apply button")
        except Exception:
            pass  # Already on the application form

        print("Filling form...")
        fill_ashby_form(page, cover_letter_path, extra_answers)

        print("\n✅ All fields filled. Submitting in 5 seconds... (close browser to cancel)")
        time.sleep(5)

        # Click Submit
        submit_btn = page.locator("button[type='submit']:has-text('Submit'), button:has-text('Submit application'), button:has-text('Apply')").first
        try:
            submit_btn.click()
            print("Clicked submit")
            time.sleep(4)
        except Exception as e:
            print(f"Submit button issue: {e}")

        content = page.content()
        if any(w in content.lower() for w in ["thank you", "application received", "submitted", "we've received", "successfully"]):
            print("✅ Application submitted successfully!")
        else:
            print("⚠️  Check browser — may need manual confirmation.")
            time.sleep(20)

        browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 apply_ashby.py <job_url> <cover_letter_path> [answers_json]")
        sys.exit(1)

    url = sys.argv[1]
    cl_path = sys.argv[2]
    answers = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    run(url, cl_path, answers)
