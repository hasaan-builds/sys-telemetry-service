# 🚀 Daily AI Content Engine — Deployment Guide

This repository contains a **turnkey, 100% free, 24/7 automated content engine** powered by **GitHub Actions** and **Telegram Bot API**.

Every day at **12:00 PM UTC** (or whenever manually triggered), the engine:
1. **Scrapes** trending AI repositories and developer tools from GitHub.
2. **Deduplicates** against `posted_ids.json`.
3. **Generates** high-converting, proof-driven post copy in the blended **Jayed voice** (Nick/Roy/Nate/Jack).
4. **Packages** the post and 1st-comment into an **upgraded Telegram Card** featuring 1-click copy code blocks (`<pre>...</pre>`), unicode divider borders, and hook blockquotes.
5. **Dispatches** directly to your Telegram channel.
6. **Commits** updated state back to GitHub to **reset GitHub's 60-day scheduled workflow inactivity timer forever**.

---

## ⚡ 3-Step Setup Guide

### Step 1: Push to GitHub

Open your terminal in this directory (`GitHub deployment`) and push the repository to your GitHub account:

```bash
# 1. Initialize git repository
git init

# 2. Stage all files
git add .

# 3. Commit deployment package
git commit -m "feat: initial commit for daily content engine"

# 4. Set default branch to main
git branch -M main

# 5. Link your GitHub repository (replace with your repo URL)
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/<YOUR_REPO_NAME>.git

# 6. Push code to GitHub
git push -u origin main
```

---

### Step 2: Add 2 Repository Secrets

Your bot credentials are kept secure using GitHub Secrets (never committed to git).

1. Navigate to your repository on **GitHub.com**.
2. Click **Settings** (top navigation tab).
3. In the left sidebar, expand **Secrets and variables** → click **Actions**.
4. Click the green **New repository secret** button.
5. Add the following **2 secrets**:

| Secret Name | Value Example | Description |
| :--- | :--- | :--- |
| `BOT_TOKEN` | `8860542665:AAHxegKH...` | Your Telegram Bot token from [@BotFather](https://t.me/BotFather) |
| `CHANNEL` | `8526562130` or `@YourChannel` | Your Telegram Channel ID or `@channel_handle` |

---

### Step 3: Done! (Automatic 24/7 Runs & 1-Click Manual Trigger)

You're done! The engine is now active and will run automatically every day at **12:00 PM UTC**.

#### How to test with 1 click right now:
1. In your GitHub repository, click the **Actions** tab.
2. In the left sidebar, click **Daily AI Content Engine**.
3. Click the **Run workflow** dropdown on the right side.
4. Click the green **Run workflow** button.
5. Watch the real-time execution logs. Within ~45 seconds, the styled card with your 1-click copy post and auto-reply comment will arrive directly in your Telegram channel!

---

## 🛠 Local Dry-Run Testing

You can also run and preview the engine locally on your computer at any time without sending messages to Telegram:

```bash
# Preview the next trending AI repo and post copy without dispatching
python daily_engine.py --dry-run
```

To run a live test locally using your `.env` file:
```bash
# Ensure .env contains BOT_TOKEN and CHANNEL
python daily_engine.py
```

---

## 📁 Repository Structure

```text
.
├── .github/
│   └── workflows/
│       └── daily-engine.yml    # Daily cron workflow & commit persistence
├── .gitignore                  # Ignores .env, pycache, temporary files
├── DEPLOYMENT_GUIDE.md         # This 3-step setup guide
├── daily_engine.py             # Scraper, Jayed voice generator & orchestrator
├── posted_ids.json             # Deduplication database (tracks posted repos)
├── requirements.txt            # Python dependencies (requests, bs4, playwright)
└── send_to_telegram.py         # Resilient Telegram HTML card dispatcher
```

---

## 🔒 Security & Best Practices
- **No secrets in git**: `.env` is ignored by `.gitignore`.
- **Inactivity timer reset**: Every scheduled run commits back to the repo using `github-actions[bot]`, ensuring GitHub never disables your cron schedule due to repository inactivity.
