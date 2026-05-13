# Opening the TradingAgents Dashboard on Your Oracle Cloud Server

This guide walks you through making the Streamlit dashboard available in your browser. There are three parts: open the port in Oracle's firewall, open the port in Ubuntu's firewall, and install the background service. Once done, you just visit a URL.

---

## Part 1 — Open Port 8501 in the Oracle Cloud Console

Oracle Cloud has its own firewall called a **Security List**. You need to add a rule that allows traffic on port 8501.

1. Log in to [cloud.oracle.com](https://cloud.oracle.com) and open the hamburger menu (three horizontal lines, top-left).
2. Go to **Networking** → **Virtual Cloud Networks**.
3. Click on your VCN (it will be named something like `vcn-YYYYMMDD-HHMM` or whatever you chose when you created the instance).
4. In the left sidebar under **Resources**, click **Security Lists**.
5. Click on the security list named **Default Security List for ...** (the one attached to your subnet).
6. Click the **Add Ingress Rules** button.
7. Fill in the form exactly as follows:

   | Field | Value |
   |---|---|
   | Source Type | CIDR |
   | Source CIDR | `0.0.0.0/0` |
   | IP Protocol | TCP |
   | Source Port Range | (leave blank) |
   | Destination Port Range | `8501` |
   | Description | Streamlit dashboard |

8. Click **Add Ingress Rules** to save.

The Oracle-side firewall is now open. Traffic on port 8501 can reach your server.

---

## Part 2 — Open Port 8501 in the Ubuntu Firewall

Ubuntu has its own firewall (iptables) that also needs to allow port 8501. SSH into your server and run these commands one at a time.

**Add the rule:**
```bash
sudo iptables -I INPUT -p tcp --dport 8501 -j ACCEPT
```

**Save it so it survives a reboot:**
```bash
sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
```

If `iptables-persistent` is already installed, just run the second line (the save command).

---

## Part 3 — Install the Dashboard as a Background Service

This installs Streamlit as a service that starts automatically and keeps running even after you close your SSH session.

SSH into your server, then run all of these commands in order:

**Step 1 — Copy the service file into place:**
```bash
mkdir -p ~/.config/systemd/user
cp /opt/tradingagents/deploy/streamlit-user.service.example \
   ~/.config/systemd/user/streamlit-tradingagents.service
```

**Step 2 — Tell Streamlit to listen on a public address (not just localhost):**
```bash
sed -i '/\[Service\]/a Environment=STREAMLIT_SERVER_ADDRESS=0.0.0.0' \
   ~/.config/systemd/user/streamlit-tradingagents.service
```

**Step 3 — Make the startup script executable:**
```bash
chmod +x /opt/tradingagents/scripts/run-streamlit-headless.sh
```

**Step 4 — Load and start the service:**
```bash
systemctl --user daemon-reload
systemctl --user enable --now streamlit-tradingagents.service
```

**Step 5 — Allow the service to keep running after you log out:**
```bash
sudo loginctl enable-linger ubuntu
```

---

## Part 4 — Open the Dashboard

Find your server's public IP address in the Oracle Cloud console (go to **Compute** → **Instances** → click your instance — the public IP is listed there).

Then open a browser on any device and go to:

```
http://YOUR_SERVER_IP:8501
```

Replace `YOUR_SERVER_IP` with the actual IP address. No VPN, no SSH tunnel — just paste it in and hit Enter.

---

## Part 5 — Check Status and Restart

**Check if the service is running:**
```bash
systemctl --user status streamlit-tradingagents.service
```

You should see `Active: active (running)`. If something looks wrong, read the last few log lines shown there.

**View the full logs:**
```bash
journalctl --user -u streamlit-tradingagents.service -n 50
```

**Restart the service** (use this any time you make changes or something freezes):
```bash
systemctl --user restart streamlit-tradingagents.service
```

**Stop the service:**
```bash
systemctl --user stop streamlit-tradingagents.service
```

**Start it again after stopping:**
```bash
systemctl --user start streamlit-tradingagents.service
```
