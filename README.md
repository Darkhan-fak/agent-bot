# 🤖 AgentBot

> Your phone is now a remote control for an AI coding agent.
> Text a task → Claude writes code on your machine → approve deploys from bed.

---

## 🛠️ Why AgentBot?

Imagine you are out for a coffee or on a bus and realize a critical bug or a simple feature you want to implement. Instead of waiting until you get home to open your laptop:
1. You text the task to your private Telegram bot.
2. The Claude-powered agent executes tool-use steps directly on your workstation or server.
3. It installs dependencies, writes the code, runs the test suite, and formats the project.
4. For critical actions (like deployments or typing in API secrets), the bot sends interactive buttons or prompt dialogues.
5. Once you approve, the task is finished, and the bot sends a summary back to your phone.

---

## 💬 Chat Interaction Showcase

Here is how a real session interaction with `AgentBot` looks directly from Telegram:

```
[Console Startup Log]
🔑 One-time Telegram auth passcode generated: [ 8329 ]
------------------------------------------------------

[Telegram Chat with @MyPrivateCoderBot]

👤 User:
/start

🤖 Bot:
🔐 Bot session is currently locked.
Please enter your 4-digit terminal passcode:
Command: `/auth <code>`

👤 User:
/auth 8329

🤖 Bot:
✅ Session unlocked successfully!
Authorized User ID: 123456789
Working directory: /Users/darkhan/Desktop/Private/agent-bot

👤 User:
Run the test suite and verify if tests pass.

🤖 Bot:
🧠 Agent starting task...
📂 Listing workspace files...
🛠️ Executing: `python -m pytest`
...
✅ Task completed!
All 8 test cases passed successfully.

👤 User:
/status

🤖 Bot:
💤 Agent is currently idle. Ready for your next coding task!
```

---

## 📂 Architecture

Below is the workflow showing how AgentBot safely communicates between Telegram and your local directory:

```
┌──────────────┐         ┌───────────────────┐         ┌───────────────────┐
│   Telegram   │────────▶│   Telegram Bot    │────────▶│   Claude Agent    │
│  On Mobile   │◀────────│ (python-telegram- │◀────────│  (Anthropic SDK)  │
│  or Desktop  │         │     bot v20+)     │         │   claude-3-5-...  │
└──────────────┘         └───────────────────┘         └─────────┬─────────┘
        │                          │                             │
        │                          │                             │
        │ 🔐 Callback approvals    │ ⚙️ Subprocesses & Files      │ 🛠️ Tool calls
        └──────────────────────────┴──────────────┬──────────────┴─────────┘
                                                  ▼
                                       ┌───────────────────┐
                                       │   Tool Executor   │
                                       ├───────────────────┤
                                       │ • run_command     │
                                       │ • read_file       │
                                       │ • write_file      │
                                       │ • list_files      │
                                       │ • request_approval│
                                       └──────────┬────────┘
                                                  │
                                                  ▼
                                       ┌───────────────────┐
                                       │  Local Filesystem │
                                       │    (WORK_DIR)     │
                                       └───────────────────┘
```

---

## 🔐 Safety & Security Features

Since AgentBot can execute commands and write files on your local computer, security is the top priority:

1. **User ID Whitelisting**: The bot ignores every single request that does not originate from your specific `ALLOWED_USER_ID` configured in the `.env` file.
2. **Robust Path Traversal Prevention**: Every file read, write, or list command resolves paths using Python's `pathlib.Path.resolve()` and checks that it is strictly located inside your configured `WORK_DIR`. Escaping the folder using `..` is completely blocked and raises a `PermissionError`.
3. **Command Blocklist**: `run_command` actively blocks dangerous/destructive operations (e.g. `sudo`, `rm -rf /`, `format`, `mkfs`, etc.) and returns a safety warning instead.
4. **Interactive Approval Flow**: Dangerous operations (such as deploy or deleting database tables) must request your manual approval using inline keyboard buttons.
5. **Secure Ephemeral Secrets**: If the agent requires you to type a secret key (e.g., API tokens), the bot prompts you, captures the input, feeds it to the agent, and immediately deletes the secret message from the Telegram chat history.

---

## ⚙️ Quick Start

### 1. Requirements & Dependencies
Make sure you have Python 3.8+ installed on your machine.
Clone the repository and install the dependencies:
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and fill in the required values:
```bash
cp .env.example .env
```
Update these keys:
*   `TELEGRAM_TOKEN`: Get this from [@BotFather](https://t.me/BotFather).
*   `ALLOWED_USER_ID`: Get your numeric Telegram ID from [@userinfobot](https://t.me/userinfobot) or similar.
*   `ANTHROPIC_API_KEY`: Your Claude API token.
*   `WORK_DIR`: The root directory for the agent workspace (e.g., `~/projects` or a specific dev directory).

### 3. Run the Bot
Run the bot directly via:
```bash
python -m agent_bot
```

### 4. Bot Commands
*   `/start`: Check that the bot is alive.
*   `/status`: Inspect what the agent is currently working on.
*   `/cancel`: Interrupts and terminates the active running agent task immediately.
*   `/dir <path>`: View or dynamically change the current `WORK_DIR` (must be a valid directory path).

---

## 🧪 Testing

The safety features of the path traversal check and the command blocklist are covered by pytest. Run the tests using:
```bash
pytest tests/
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
