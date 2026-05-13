# Mac + Oracle server: SSH, UI tunnel, git pull, Streamlit

Replace paths if yours differ (SSH key, IP, repo directory on the server).

---

## 1. SSH into the server (shell work)

**On your Mac** (Terminal, prompt like `michaelandonia@...`):

```bash
ssh -i ~/Downloads/ssh-key-2026-05-12.key ubuntu@141.147.118.172
```

You should see `ubuntu@triad:~$` (or similar). Use this for `git pull`, `tmux`, `bootstrap`, editing `.env`, etc.

**Do not** run Mac-style paths on the server (e.g. `~/Downloads/...pem` does not exist on the VM).

---

## 2. Open the website (Streamlit UI)

The UI runs on the **VM** at `127.0.0.1:8501`. Your Mac reaches it through an **SSH tunnel**.

> **Important:** Run the tunnel command **only on your Mac** (`michaelandonia@…`).  
> If you are already logged in as `ubuntu@triad` on the server, **do not** run `-i ~/Downloads/…` there — that path is on the Mac, not the VM, and you will get `Permission denied (publickey)`.

**On the Mac**, open a **second** Terminal window (keep it open while you browse):

```bash
ssh -i ~/Downloads/ssh-key-2026-05-12.key -N -L 8501:127.0.0.1:8501 ubuntu@141.147.118.172
```

- This window will look “idle” — that is normal (`-N` = no remote shell, only the tunnel).
- **Leave it open** while you use the UI.

**In the browser on the Mac:**

```text
http://127.0.0.1:8501
```

**Not** the Oracle public IP for this setup (Streamlit is bound to localhost on the VM).

To stop the UI in the browser: close the tab. To stop the tunnel: focus the tunnel terminal and press **Ctrl+C**.

---

## 3. Update code on the server (`git pull`)

SSH in (section 1), then:

```bash
cd /opt/tradingagents
git pull
```

If `origin` is your fork, this pulls the latest `main` from GitHub.

After code changes that affect dependencies:

```bash
. .venv/bin/activate
pip install -e .
deactivate
```

---

## 4. Start / restart the Streamlit UI service (always-on)

The UI is usually managed by **systemd user** (survives disconnect if **linger** is enabled).

```bash
systemctl --user daemon-reload
systemctl --user restart streamlit-tradingagents.service
systemctl --user status streamlit-tradingagents.service --no-pager
```

Quick check on the VM:

```bash
curl -sI http://127.0.0.1:8501 | head -5
```

**One-time (so user services keep running after logout):**

```bash
sudo loginctl enable-linger "$USER"
```

---

## 5. Long jobs without the Mac (e.g. `bootstrap`)

Run heavy commands **inside `tmux` on the server** so closing the laptop does not kill the job.

```bash
ssh … ubuntu@141.147.118.172          # from Mac
tmux new-session -A -s boot          # create or attach session “boot”
cd /opt/tradingagents && . .venv/bin/activate && set -a && source .env && set +a && export PYTHONPATH=/opt/tradingagents
python -m cli.main advisor portfolio bootstrap
```

**Detach** (job keeps running): **Ctrl+B**, then **D**

**Later (from Mac → SSH → attach):**

```bash
tmux attach -t boot
```

If `tmux` misbehaves, use `screen` or `nohup … > ~/bootstrap.log 2>&1 &` instead.

---

## 5b. Planner calendar jobs (after bootstrap)

Bootstrap does **not** fill the planner calendar. After a full bootstrap, if you want scheduled jobs:

```bash
cd /opt/tradingagents && . .venv/bin/activate && set -a && source .env && set +a && export PYTHONPATH=/opt/tradingagents
python -m cli.main advisor portfolio replan --force
```

---

## Quick reference

| Goal | Where | Command |
|------|--------|---------|
| Server shell | Mac | `ssh -i ~/Downloads/ssh-key-2026-05-12.key ubuntu@141.147.118.172` |
| Browser UI | Mac | Tunnel (above), then `http://127.0.0.1:8501` |
| Pull latest code | VM | `cd /opt/tradingagents && git pull` |
| Restart Streamlit | VM | `systemctl --user restart streamlit-tradingagents.service` |
| Long bootstrap | VM + tmux | `tmux new-session -A -s boot` → run bootstrap → **Ctrl+B** **D** |

---

## Troubleshooting

- **`Permission denied (publickey)`** from the Mac: wrong key path or wrong user; use the **Mac** path to `.key` / `.pem`.
- **`Permission denied`** when SSHing **from the VM to the VM** with `-i ~/Downloads/...`:** the key is on the Mac, not the server.
- **Streamlit “Deploy” popup** (Community Cloud): not your advisor — close it. Use the in-page **Deploy** under “Deploy and automation” for advisor init only.
- **Email / Slack summaries:** configure `TRADINGAGENTS_ANALYSIS_WEBHOOK_URL` and/or full SMTP + `TRADINGAGENTS_ANALYSIS_EMAIL_*` in **`/opt/tradingagents/.env` on the VM**.
