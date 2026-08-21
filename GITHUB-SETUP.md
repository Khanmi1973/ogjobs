# Put the dashboard online (free) — step by step

When this is done you will have a web link like:

```
https://YOURNAME.github.io/ogjobs/
```

Open it on your phone anywhere in the world. Your PC can be switched off.
It updates itself once a day, and there is a **Refresh jobs** button when you
want it sooner.

Cost: **£0**. You need a free GitHub account and about 10 minutes, once.

---

## First, the one thing to decide

Free hosting on GitHub requires the repository to be **public**. That means
anyone who finds the link can see your job list.

- What is in it: job adverts that are already public on company websites.
- What is **not** in it: your name, your CV, your email, your applications.

If that is fine, carry on. **Do not put your CV or any personal document in
this folder**, because it would become public too.

---

## Step 1 — Make a GitHub account

Go to <https://github.com> and sign up. Free plan. Remember your username.

## Step 2 — Install Git

Download from <https://git-scm.com/download/win> and install it. Click Next on
everything; the defaults are fine.

Close and reopen any PowerShell window afterwards, then check it worked:

```bash
git --version
```

## Step 3 — Create an empty repository on GitHub

1. Go to <https://github.com/new>
2. **Repository name:** `ogjobs`
3. Choose **Public**
4. Do **not** tick "Add a README file"
5. Click **Create repository**

Leave that page open — you will need the URL it shows.

## Step 4 — Upload your folder

In PowerShell, run these one at a time. Replace `YOURNAME` with your GitHub
username.

```bash
cd C:\cdx\ogjobs
```

```bash
git init -b main
```

```bash
git add -A
```

```bash
git commit -m "Oil and gas job radar"
```

```bash
git remote add origin https://github.com/YOURNAME/ogjobs.git
```

```bash
git push -u origin main
```

A browser window will pop up asking you to sign in to GitHub. Do that, and the
upload finishes.

## Step 5 — Let the robot write to your repository

1. On GitHub open your repo → **Settings** → **Actions** → **General**
2. Scroll to **Workflow permissions**
3. Select **Read and write permissions**
4. Click **Save**

Without this, the scan runs but cannot publish the result.

## Step 6 — Run the first scan

1. Open your repo → **Actions** tab
2. If it asks, click the green **I understand my workflows, go ahead and enable them**
3. On the left click **Scan jobs**
4. On the right click **Run workflow** → then the green **Run workflow** button

It takes about 5–15 minutes. A yellow dot means running, green tick means done.

## Step 7 — Switch on the website

1. Repo → **Settings** → **Pages**
2. Under **Source** choose **Deploy from a branch**
3. Branch: **main**, folder: **/docs**
4. Click **Save**

Wait 1–2 minutes, then reload that page. It will show your link:

```
https://YOURNAME.github.io/ogjobs/
```

Open it on your phone. Add it to your home screen and it works like an app.

---

## Using it day to day

- **It refreshes itself every day** at 05:00 UTC. Just open the link.
- **Want fresh jobs right now?** Press **Refresh jobs** on the page. It opens
  GitHub; press **Run workflow**, wait about 5 minutes, then pull down to
  reload the dashboard.
- **Changed your filters?** Edit `config/filters.json` on your PC, then:

```bash
cd C:\cdx\ogjobs && git add -A && git commit -m "new filters" && git push
```

---

## If something goes wrong

**The Actions run has a red X.**
Click it and read the failed step. The usual cause is Step 5 not being done.

**The page says 404.**
Pages was not switched on, or the first scan has not finished. Check that
`docs/index.html` exists in your repo, then redo Step 7.

**The dashboard is empty or has fewer jobs than on your PC.**
Some career sites block requests coming from datacentres, which is where
GitHub's computers live, even though they answer your home connection fine.
Open the Actions run and look at the log to see which sources failed. Anything
blocked there still works when you scan from your own PC with `dashboard.bat` —
the two methods share the same database, so you can use both.

**I want it private.**
Private repositories need a paid GitHub plan for Pages. The free alternative is
to keep using `mobile.bat` on your own Wi-Fi, or copy `jobs.html` to your phone.

---

## Which method should I use?

| | Works with PC off | Scan button | Private |
|---|---|---|---|
| **GitHub Pages** (this guide) | yes | yes, via GitHub | no, public |
| **`mobile.bat`** on your Wi-Fi | no | yes, instant | yes |
| **Copy `jobs.html`** to phone | yes, offline too | no | yes |

Most people want GitHub Pages for everyday phone use, and `dashboard.bat` on the
PC when tuning filters.
