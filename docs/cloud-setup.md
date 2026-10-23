# Cloud setup checklist

These steps need your own GitHub, Anthropic Console and Streamlit accounts, so they're done
by hand once. Everything else (the pipeline, review flow and dashboard cloud mode) is in the
repository.

## 1. GitHub repository

1. Create a **public** repository named `fare-watch` with no README, license or .gitignore
   (this folder already has them).
2. **Before the first push**, turn on secret scanning and push protection:
   Settings -> Code security -> Secret protection.
3. Push this folder:

   ```bash
   git remote add origin https://github.com/<you>/fare-watch.git
   git push -u origin main
   ```

4. Add Actions secrets (Settings -> Secrets and variables -> Actions -> New repository secret):

   | Secret | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | Your class Claude Console key |
   | `ANTHROPIC_WORKSPACE_ID` | Your Console workspace ID (only if your key needs it) |
   | `TYPESAFE_API_KEY` | Your Jev key from console.typesafe.ai/keys (optional; without it Claude classifies) |

5. Settings -> Actions -> General -> Workflow permissions: **Read and write permissions**
   (the pipeline pushes the `data` branch with the built-in token).

## 2. Two fine-grained tokens for the dashboard

Create both at github.com -> Settings -> Developer settings -> Fine-grained tokens, limited
to **only the fare-watch repository**:

| Token | Repository permissions |
|---|---|
| `GH_DATA_TOKEN` | Contents: Read-only |
| `GH_ACTIONS_TOKEN` | Actions: Read and write (Release/Reject and the demo button) |

## 3. First pipeline run

Actions -> pipeline -> Run workflow, `minutes` = 3, `kill_switch` on (free). This creates
the `data` branch. Check the run log shows one import per minute.

## 4. Streamlit Community Cloud

1. share.streamlit.io -> Create app -> this repository, branch `main`, main file
   `dashboard/app.py`. Streamlit installs from `requirements.txt`.
2. App settings -> Secrets: paste `.streamlit/secrets.toml.example` and fill it in. The
   reviewer passcode protects Release / Reject: visitors can watch, only you can decide.
3. Open the app. The Live run page should say **Cloud mode** and replay the latest run.

## 5. Demo run (the milestone's bar)

1. Wake the app a few minutes before the demo (free apps sleep when nobody visits).
2. In the app's sidebar, **Run 30-minute demo** (needs the reviewer passcode), or
   Actions -> pipeline -> Run workflow, `minutes` = 15-30. With the kill switch off this
   spends class credits: roughly $0.50 an hour with Haiku (check current pricing); the
   agent's daily token cap in `config.toml` stops model calls if it's reached.
3. Watch the public app update every minute. If an import is held, Release or Reject it
   with your passcode; the decision shows after the running pipeline's next minute.

## 6. Daily report

Set up the Claude Routine in `docs/routine.md`, or uncomment the schedule in
`.github/workflows/daily-report.yml` if Routines aren't available.

## Limits to check

These change, so check current figures: GitHub Actions minutes and maximum job length,
Streamlit Community Cloud resources, and whether scheduled workflows have been paused
(GitHub pauses them in public repos after 60 days without activity).
