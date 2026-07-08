# Job Hunting System — How to Use

## Setup (one-time)

1. Copy `config.example.json` to `config.json`.
2. Fill in your own name, contact info, resume path, target titles/locations/salary, and ATS answers. `config.json` is gitignored so your personal data never gets committed.
3. Point `resume_path` at the absolute path of your resume PDF on disk.

## Daily Workflow (takes ~10 minutes)

### 1. Run Today's Search
Tell Claude Code:
> "Run my job search for today"

Claude will search Indeed for all your target titles across Austin TX and remote, score each job against your profile, add matches to your tracker, and show you a prioritized list.

### 2. Review Priority Matches
Claude will highlight **Priority** jobs (score 8–10) and offer to generate cover letters immediately.

To get a cover letter:
> "Generate a cover letter for [Job Title] at [Company]"

Cover letters are saved to `job_hunter/cover_letters/` named as `YYYY-MM-DD_Company_Title.md`.

### 3. Update Application Status
After you apply, tell Claude:
> "Mark [Company] [Title] as applied"

Or to update any status:
> "Update [Company] status to interviewing / rejected / offer"

Valid statuses: `Found` → `Review` → `Priority` → `Applied` → `Interviewing` → `Offer` → `Rejected` → `Passed`

### 4. Weekly Pipeline Review
Ask Claude:
> "Show me my job pipeline summary"

Claude will read your tracker and give you a status breakdown with follow-up reminders.

---

## Files in This System

| File | Purpose |
|------|---------|
| `config.json` | Your profile, target roles, and search preferences |
| `tracker.csv` | Master list of all jobs found and their status |
| `SCORING_RUBRIC.md` | How Claude scores each job for fit |
| `COVER_LETTER_TEMPLATE.md` | Rules Claude follows when writing your cover letters |
| `cover_letters/` | All generated cover letters, one file per application |

---

## Customizing Your Search

To change target titles, locations, or salary — edit `config.json`.  
To adjust how Claude scores jobs — edit `SCORING_RUBRIC.md`.  
To change cover letter style — edit `COVER_LETTER_TEMPLATE.md`.

---

## Setting Up Daily Automated Search

To have Claude search automatically every morning, tell Claude:
> "Schedule my job search to run every weekday at 8am"
