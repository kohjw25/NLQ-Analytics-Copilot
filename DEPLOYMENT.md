# Deploying Insight Copilot — a step-by-step guide for beginners

This guide takes you from "it runs on my laptop" to "it has a public web address
anyone can open." No prior deployment experience assumed. We use **Streamlit
Community Cloud** — it's free, needs no credit card, and (paired with a free
OpenRouter model) costs nothing to run.

**What you'll end up with:** a URL like `https://your-app-name.streamlit.app` that
loads the Insight Copilot app.

**Roughly how long:** 20–30 minutes the first time.

---

## Overview of the whole process

1. Install Git and create a GitHub account (one-time setup).
2. Get a free OpenRouter API key (this is what powers the "Ask" feature).
3. Upload the project to GitHub.
4. Connect GitHub to Streamlit Community Cloud and deploy.
5. Paste your API key into Streamlit's Secrets box.
6. Open your live URL and test it.

Then: how to update the app, how to limit who can use it, and (optional) an
advanced path using Docker + Google Cloud Run.

---

## Part 1 — One-time setup: Git and GitHub

**Git** is a tool that tracks your code. **GitHub** is a website that stores it
online. Streamlit reads your code from GitHub.

1. **Create a GitHub account** (free): go to <https://github.com>, click **Sign up**,
   follow the prompts. Remember your username — you'll need it.

2. **Install Git** on your computer:
   - Windows: download from <https://git-scm.com/download/win> and run the
     installer. Click **Next** through every screen (defaults are fine).
   - Mac: open the Terminal app and type `git --version`. If it isn't installed,
     macOS will offer to install it — accept.

3. **Check it worked.** Open a terminal (Windows: search "Git Bash" or
   "PowerShell"; Mac: "Terminal") and run:
   ```bash
   git --version
   ```
   You should see a version number like `git version 2.44.0`.

---

## Part 2 — Get a free OpenRouter API key

An "API key" is a password that lets the app talk to an AI model. OpenRouter
offers free models, so this costs nothing.

1. Go to <https://openrouter.ai> and click **Sign in** (you can use your Google or
   GitHub account).
2. Once signed in, go to <https://openrouter.ai/keys>.
3. Click **Create Key**, give it a name like `insight-copilot`, and click create.
4. **Copy the key immediately** — it looks like `sk-or-v1-abc123...`. Paste it
   somewhere safe (a notes app) for a minute. You won't be able to see it again
   later; if you lose it you just make a new one.

> ⚠️ Treat this key like a password. Never paste it into your code or share it
> publicly. We'll put it in a secure "Secrets" box, not in the code.

---

## Part 3 — Put the project on GitHub

You'll create an empty repository ("repo") on GitHub, then push your code to it.

### 3a. Create the empty repo on GitHub

1. Go to <https://github.com/new>.
2. **Repository name:** type `insight-copilot` (or any name).
3. Leave it **Public** (required for the free Streamlit tier). Private repos also
   work but need a paid GitHub/Streamlit plan.
4. **Do NOT** check "Add a README" / ".gitignore" / "license" — leave those
   unchecked, because your project already has files.
5. Click **Create repository**.
6. On the next page you'll see a URL like
   `https://github.com/YOUR-USERNAME/insight-copilot.git`. Copy it.

### 3b. Push your code

Open a terminal **in the project folder** (the folder that contains
`streamlit_app.py`). On Windows you can right-click the folder and choose
"Open in Terminal" or "Git Bash Here". Then run these commands one at a time,
replacing the URL with yours from step 3a:

```bash
# (first time on this computer only) tell Git who you are
git config --global user.name "Your Name"
git config --global user.email "you@example.com"

# stage and commit everything that isn't gitignored
git add .
git commit -m "Add Insight Copilot app and deployment files"

# connect this folder to your GitHub repo and upload
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/insight-copilot.git
git push -u origin main
```

- If Git asks you to log in, a browser window will open — sign in to GitHub and
  authorize it. (If it asks for a password in the terminal instead, GitHub no
  longer accepts your account password there; use the browser sign-in, or create
  a "Personal Access Token" at github.com → Settings → Developer settings.)
- `git remote add origin` errors with "remote origin already exists"? Run
  `git remote set-url origin https://github.com/YOUR-USERNAME/insight-copilot.git`
  instead, then `git push -u origin main`.

**Verify:** refresh your GitHub repo page in the browser. You should now see all
the project files (`streamlit_app.py`, `insight_copilot/`, `requirements.txt`, …).

> Note: your API key is **not** uploaded (it lives only in your head / notes for
> now), and `ab_data.csv` is intentionally excluded by `.gitignore`. The app still
> works online because it ships the sample dataset and accepts browser uploads.

---

## Part 4 — Deploy on Streamlit Community Cloud

1. Go to <https://share.streamlit.io> and click **Sign in** → **Continue with
   GitHub**. Authorize Streamlit when asked (this lets it read your repo).
2. Click **Create app** (or **New app**), then choose **Deploy a public app from
   GitHub**.
3. Fill in the form:
   - **Repository:** `YOUR-USERNAME/insight-copilot`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`  ← important: the file at the repo
     root, not the one inside `insight_copilot/`.
4. Click **Advanced settings**:
   - **Python version:** choose **3.12** (stable and fully compatible).
   - **Secrets:** paste the following (replace with your real key). This is the
     secure place for your key — it is not visible to app visitors:
     ```toml
     OPENROUTER_API_KEY = "sk-or-v1-your-real-key"
     INSIGHT_COPILOT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
     ```
5. Click **Save**, then **Deploy**.
6. Wait 2–5 minutes. You'll see a build log scrolling ("Installing
   dependencies…"). When it finishes, the app opens automatically.

**Your app is now live** at a URL shown in the address bar, e.g.
`https://insight-copilot-xxxx.streamlit.app`. That's the link you share.

---

## Part 5 — Test it

1. In the app's left sidebar, click **"Use sample e-commerce dataset"**.
2. The sidebar should show **Query engine** with an OpenRouter model selected —
   use the dropdown to try different free models.
3. Go to the **Ask** tab and type: *"Which region had the highest revenue?"* then
   click **Answer**.
4. You should get a sentence, a chart, a table, and a "How this was calculated"
   panel.

If the answer looks wrong or you see a rate-limit note, pick a different free
model from the sidebar dropdown and try again (see Troubleshooting).

---

## Part 6 — Updating the app later

Any time you change the code, just push again and Streamlit redeploys
automatically:

```bash
git add .
git commit -m "Describe what you changed"
git push
```

Within a minute or two the live app updates itself. To change your API key or
model, use the app's **Settings → Secrets** (the ⋮ / "Manage app" menu on
share.streamlit.io) — no code change needed.

---

## Part 7 — Controlling who can use it, and cost

- **Cost:** with a `:free` model, there is no charge. Free models have **daily
  limits** and can be slow; if many people use your public link, you may hit the
  limit and the app will fall back to its offline rule-based generator (it says so
  in the trust panel). No surprise bills.
- **Restrict viewers:** on share.streamlit.io, open your app's settings and use
  **Sharing** to limit access to specific email addresses if you don't want it
  fully public.
- **Upgrade quality later:** if free models aren't reliable enough, add a tiny
  amount of credit to OpenRouter and switch the model (in the sidebar or the
  `INSIGHT_COPILOT_MODEL` secret) to a cheap paid one — often a fraction of a cent
  per question. Or set `ANTHROPIC_API_KEY` instead to use Claude.

---

## Part 8 (optional, advanced) — Docker + Google Cloud Run

Use this only if you outgrow Streamlit Community Cloud (need more power, a custom
domain, or private networking). It costs a little and assumes some comfort with
the command line. The repo already includes a `Dockerfile`.

1. Install the Google Cloud CLI: <https://cloud.google.com/sdk/docs/install>.
2. Create a Google Cloud project and enable billing (Cloud Run has a free tier).
3. In a terminal in the project folder:
   ```bash
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   gcloud run deploy insight-copilot \
     --source . \
     --region us-central1 \
     --allow-unauthenticated \
     --set-env-vars OPENROUTER_API_KEY=sk-or-...,INSIGHT_COPILOT_MODEL=meta-llama/llama-3.3-70b-instruct:free
   ```
4. Cloud Run builds the container from the `Dockerfile` and returns a public URL.

The same `Dockerfile` works on Render, Fly.io, AWS App Runner, and Azure Container
Apps — each has its own "deploy from a Dockerfile / from GitHub" flow and a place
to set the `OPENROUTER_API_KEY` environment variable.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Build fails on "Installing dependencies" | Confirm **Main file path** is `streamlit_app.py` and Python version is **3.12**. Check the build log for the failing package. |
| App loads but sidebar says "rule-based (no API key)" | Your secret isn't set. Open **Manage app → Settings → Secrets** and confirm `OPENROUTER_API_KEY = "..."` is there (with quotes). Save; the app reboots. |
| "ModuleNotFoundError: insight_copilot" | Main file path must be the root `streamlit_app.py` (not `insight_copilot/app.py`). |
| Answers are poor or you see a "rate limited"/"fallback" note | Free models are limited. Pick another model in the sidebar dropdown, or add OpenRouter credit and use a cheap paid model. |
| "remote origin already exists" during `git push` | Run `git remote set-url origin <your repo URL>` then push again. |
| Git push asks for a password and rejects it | GitHub needs browser sign-in or a Personal Access Token, not your account password. See Part 3b. |

---

## Quick reference

- **Local run:** `pip install -r requirements.txt` then
  `streamlit run streamlit_app.py`
- **Deploy entrypoint:** `streamlit_app.py` (repo root)
- **Secrets (cloud):** Settings → Secrets, TOML format
- **Secrets (local):** copy `.streamlit/secrets.toml.example` to
  `.streamlit/secrets.toml`
- **Switch model:** sidebar dropdown, or the `INSIGHT_COPILOT_MODEL` secret
