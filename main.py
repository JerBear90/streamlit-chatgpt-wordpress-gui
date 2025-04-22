import os
import streamlit as st
import openai
import requests
import paramiko
from dotenv import load_dotenv
from git import Repo
from difflib import unified_diff
from datetime import datetime
import re
import time

# ✅ MUST be first Streamlit call
st.set_page_config(page_title="Studio7 | GPT Plugin Builder", layout="wide")

# 📦 App constants
DAILY_TOKEN_CAP = 5000
USAGE_LOG = "token_usage.log"
repo_path = os.getcwd()
plugin_path = os.path.join(repo_path, "responsive-image-pro")
plugin_file = os.path.join(plugin_path, "plugin-core.php")
os.makedirs(plugin_path, exist_ok=True)

# 🔧 Load environment
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
THREAD_ID = os.getenv("CHAT_THREAD_ID")
FTP_HOST = os.getenv("FTP_HOST")
FTP_PORT = int(os.getenv("FTP_PORT", 22))
FTP_USER = os.getenv("FTP_USER")
FTP_PASS = os.getenv("FTP_PASS")

# 🧼 UI Log setup
log_box = st.empty()
log_history = []

def log(msg, level="info"):
    emoji = {"info": "ℹ️", "success": "✅", "error": "❌", "warn": "⚠️"}
    log_history.append(f"{emoji.get(level, '')} {msg}")
    log_box.code("\n".join(log_history[-25:]), language="text")

# 🔁 Update .env file with new thread
def update_env_thread_id(new_thread_id):
    env_path = ".env"
    if not os.path.exists(env_path):
        log("⚠️ .env file not found, skipping update.", "warn")
        return
    try:
        with open(env_path, "r") as file:
            content = file.read()
        new_content = re.sub(r"^CHAT_THREAD_ID=.*$", f"CHAT_THREAD_ID={new_thread_id}", content, flags=re.MULTILINE)
        with open(env_path, "w") as file:
            file.write(new_content)
        log(f"📝 .env file updated with new thread ID.", "info")
    except Exception as e:
        log(f"❌ Failed to update .env file: {e}", "error")

# ⚙️ Mode and thread creation toggle
mode = st.sidebar.selectbox("⚙️ Mode", ["Production", "Test Mode"])
test_mode = (mode == "Test Mode")

create_new_thread = st.sidebar.toggle("🧼 Start fresh with a new thread", value=False)
if create_new_thread and not test_mode:
    try:
        log("🧼 Creating new thread...", "info")
        new_thread = openai.beta.threads.create()
        THREAD_ID = new_thread.id
        update_env_thread_id(THREAD_ID)
        log(f"✅ New thread ID: {THREAD_ID}", "success")
    except Exception as e:
        log(f"❌ Failed to create new thread: {e}", "error")
        st.stop()
elif create_new_thread and test_mode:
    log("🧪 Skipping thread creation — running in Test Mode.", "info")

# 📊 Token usage
def get_today_token_total():
    today = datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(USAGE_LOG):
        return 0
    with open(USAGE_LOG) as f:
        return sum(int(line.split(",")[1]) for line in f if line.startswith(today))

def log_token_usage(tokens_used):
    today = datetime.now().strftime("%Y-%m-%d")
    with open(USAGE_LOG, "a") as f:
        f.write(f"{today},{tokens_used}\n")

# 🧠 Main UI
prompt = st.text_area("Enter plugin update request", height=150)

if st.button("Generate Plugin Code"):
    if get_today_token_total() >= DAILY_TOKEN_CAP:
        log("🚫 Daily token cap reached.", "warn")
        st.stop()

    try:
        if test_mode:
            log("🧪 Test mode enabled. Using simulated plugin response.", "info")
            reply = "<?php\n// Hello World Shortcode\nfunction hello_func() { return 'Hello World'; }\nadd_shortcode('hello_world', 'hello_func');"
            tokens_used = 0
        else:
            log("🔁 Sending prompt to Assistant...", "info")
            openai.beta.threads.messages.create(thread_id=THREAD_ID, role="user", content=prompt)
            run = openai.beta.threads.runs.create(thread_id=THREAD_ID, assistant_id=ASSISTANT_ID)
            log("⏳ Awaiting response from Assistant...", "info")

            for i in range(30):
                try:
                    status = openai.beta.threads.runs.retrieve(thread_id=THREAD_ID, run_id=run.id)
                    log(f"🔄 Poll {i+1}/30 - Status: {status.status}", "info")
                    if status.status == "completed":
                        log("✅ Assistant run completed.", "success")
                        break
                    elif status.status == "failed":
                        log(f"❌ Assistant run failed. Error: {status.last_error}", "error")
                        st.stop()
                except Exception as e:
                    log(f"❌ Error polling run status: {e}", "error")
                    st.stop()
                time.sleep(1)
            else:
                log("❌ Timeout: Assistant did not respond in time.", "error")
                st.stop()

            messages = openai.beta.threads.messages.list(thread_id=THREAD_ID)
            reply = messages.data[0].content[0].text.value
            tokens_used = status.usage.total_tokens

        log_token_usage(tokens_used)
        log(f"📊 Tokens used: {tokens_used}", "info")

        old_code = []
        if os.path.exists(plugin_file):
            with open(plugin_file, "r") as old:
                old_code = old.readlines()

        with open(plugin_file, "w") as f:
            f.write(reply)
        log("✅ Plugin code written to file.", "success")

        with open(plugin_file, "r") as new:
            new_code = new.readlines()

        diff = list(unified_diff(old_code, new_code, fromfile="Before", tofile="After", lineterm=""))
        st.subheader("📄 Plugin Diff Preview")
        if diff:
            st.code("".join(diff), language="diff")
            log(f"📂 {len(diff)} lines changed in plugin.", "info")
        else:
            log("⚠️ No changes detected.", "warn")

        with open("history.txt", "a") as hist:
            hist.write("PROMPT:\n" + prompt + "\nRESPONSE:\n" + reply + "\n" + "="*80 + "\n\n")

        st.session_state['diff_ok'] = bool(diff)

    except Exception as e:
        log(f"❌ Error during GPT generation: {e}", "error")

if 'diff_ok' in st.session_state and st.session_state['diff_ok']:
    if st.button("✅ Approve & Push to GitHub"):
        try:
            repo = Repo(repo_path)
            repo.git.add(update=True)
            if repo.is_dirty():
                repo.index.commit("Approved plugin update")
                repo.remote(name='origin').push()
                log("✅ Plugin changes pushed to GitHub.", "success")
                if SLACK_WEBHOOK:
                    res = requests.post(SLACK_WEBHOOK, json={"text": "✅ Plugin updated and pushed to GitHub."})
                    if res.status_code == 200:
                        log("✅ Slack notification sent.", "success")
                    else:
                        log("⚠️ Slack notification failed.", "warn")
            else:
                log("ℹ️ Git repo clean. No changes to push.", "info")
        except Exception as e:
            log(f"❌ GitHub push error: {e}", "error")

if st.button("📦 Deploy via SFTP"):
    try:
        log("🔗 Connecting to SFTP server...", "info")
        transport = paramiko.Transport((FTP_HOST, FTP_PORT))
        transport.connect(username=FTP_USER, password=FTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)

        remote_dir = "/public_html/wp-content/plugins/responsive-image-pro"
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            sftp.mkdir(remote_dir)
            log("📁 Remote plugin folder created.", "info")

        for file in os.listdir(plugin_path):
            local = os.path.join(plugin_path, file)
            remote = f"{remote_dir}/{file}"
            sftp.put(local, remote)
            log(f"📤 Uploaded {file} to server.", "info")

        sftp.close()
        transport.close()
        log("✅ Plugin deployed to WordPress via SFTP.", "success")

    except Exception as e:
        log(f"❌ SFTP deployment failed: {e}", "error")
