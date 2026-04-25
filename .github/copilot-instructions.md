# Nano Banana – Copilot Agent Onboarding Instructions

## Project Overview

**Nano Banana** is a Python-based Discord bot that provides multi-model AI capabilities: conversational text chat (OpenAI GPT), image generation and editing (Google Gemini and OpenAI gpt-image-2), a wordplay puzzle game, usage/rate-limiting per user, and a "bot snitching" feature. The bot is built on `discord.py` (v2.4.0) with `app_commands` for slash-command support.

---

## Repository Layout

```
nanobanana/
├── bot.py              # Core Discord bot: event handlers, slash/prefix commands, business logic
├── config.py           # Loads .env and exposes all runtime configuration constants
├── model_interface.py  # Abstract BaseModelGenerator + concrete GeminiModelGenerator & GPTModelGenerator
├── image_utils.py      # Async image download helper (aiohttp → PIL Image)
├── usage_tracker.py    # Thread-safe JSON-backed per-user token/image usage + tier system
├── log_manager.py      # Rotating file logger (5 MB × 3 backups); imported once at startup
├── wordplay_game.py    # Wordplay puzzle data model, session manager, Gemini-based word/image gen
├── voice_handler.py    # Legacy voice module – voice commands are DISABLED in bot.py; do not re-enable
├── main.py             # Entry point: `python main.py`
├── run_bot.sh          # Bash launcher with environment/dependency checks
├── requirements.txt    # Python dependencies
├── .env.example        # Template for required environment variables
├── test_bot_helpers.py     # Unit tests for bot helper functions
├── test_model_interface.py # Unit tests for GPTModelGenerator API call behaviour
├── test_usage_tracker.py   # Unit tests for UsageTracker reservation/release logic
└── test_wordplay.py        # Unit tests for wordplay game session and word-pair validation
```

---

## Environment & Setup

### Required Environment Variables (`.env`)

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | Discord bot token |
| `GOOGLE_API_KEY` | Google GenAI API key (Gemini) |
| `OPENAI_API_KEY` | OpenAI API key (GPT chat + gpt-image-2) |
| `ELEVATED_USERS` | Comma-separated Discord user IDs with admin/unlimited access |
| `DEBUG_LOGGING` | `true`/`false` – enable verbose logging (default: `false`) |

Copy `.env.example` to `.env` and fill in real values before running.

### Installation & Running

```bash
pip install -r requirements.txt
python main.py
# or use the launcher script:
./run_bot.sh
```

### Python Version

Python 3.8+ is required (uses `asyncio`, `typing`, dataclasses, etc.).

---

## Key Design Decisions & Conventions

### AI Model Layer (`model_interface.py`)

- All model access goes through `BaseModelGenerator` (abstract). Never call Gemini/OpenAI SDKs directly from `bot.py`.
- `GeminiModelGenerator` uses `gemini-2.5-flash-image` for image generation and `gemini-2.5-flash` for text-only responses.
- `GPTModelGenerator` uses:
  - `gpt-image-2` via `client.images.generate(quality="medium")` for **text-prompt-only** image generation.
  - `gpt-5.4` + Responses API (`client.responses.create`) with `{"type": "image_generation", "model": "gpt-image-2"}` tool for **image-input** workflows.
  - `gpt-5.4-mini` (chat completions) for conversational replies.
- The factory function `get_model_generator(model_name)` in `model_interface.py` returns the right instance.
- All generator methods return a `(image: PIL.Image | None, text: str | None, usage_metadata: dict | None)` tuple.
- **Do not** pass `stream`, `response_format`, or `partial_images` to either the images or responses API – these parameters are unsupported and intentionally omitted (see `test_model_interface.py`).

### Usage Tracking & Rate Limiting (`usage_tracker.py`)

- Persisted in `generated_images/usage_stats.json` (thread-safe via `threading.Lock`).
- Each non-elevated user has a **tier** (`standard`=3, `limited`=2, `strict`=1, `extra`=5, `unlimited`=∞ charges).
- Each charge has an independent 8-hour expiry timer.
- The **reservation system** (`reserve_usage_slots` / `release_reserved_usage_slots`) must be used for concurrent requests so a user cannot queue more work than their tier allows. Always call `reserve_usage_slots` before starting generation and `release_reserved_usage_slots` (or `record_usage` with `consume_reserved_slots`) when done.
- Elevated users (from `config.ELEVATED_USERS`) bypass all limits.

### Logging (`log_manager.py`)

- Importing `log_manager` **configures the root logger** as a side effect. Always import it early (it is imported in `bot.py` near the top).
- Log format: `YYYY-MM-DD HH:MM:SS | LEVEL    | module: message`
- Third-party library loggers are suppressed to WARNING to keep logs clean.
- Enable debug logging at runtime via `log_manager.set_debug_logging(True)` or `DEBUG_LOGGING=true` env var.

### Bot Snitching Feature

- `tracked_messages` dict in `bot.py` stores messages that mention the bot for 8 hours.
- `on_message_delete` event handler checks if a deleted message is tracked and sends a playful call-out.
- Cleanup of expired entries happens on each new tracked-message insertion (`cleanup_old_tracked_messages()`).

### Wordplay Game (`wordplay_game.py`)

- `WordplaySession` tracks per-user attempts (3 per user), solvers, and point recipients for a single puzzle message.
- Sessions are stored in `WordplaySessionManager.sessions` keyed by Discord message ID.
- Sessions persist until explicitly removed or until the 24-hour background cleanup.
- Word-pair generation calls `generator.generate_text_only_response(prompt)` and validates output with `validate_word_pair`.

### Discord Intents & Permissions

- `intents.message_content = True` is required (enable in Discord Developer Portal).
- Slash commands are synced globally on `on_ready` via `bot.tree.sync()`.
- DM channel usage is blocked for non-elevated users.

---

## Running Tests

All tests use Python's built-in `unittest`. Run them with:

```bash
python -m pytest           # if pytest is installed, or:
python -m unittest discover # standard library alternative
```

Individual test files:

```bash
python -m unittest test_bot_helpers
python -m unittest test_model_interface
python -m unittest test_usage_tracker
python -m unittest test_wordplay
```

Tests mock external API calls (Google GenAI, OpenAI) so no real API keys are needed. `test_usage_tracker.py` uses a `tempfile.TemporaryDirectory` to avoid touching real data files.

---

## Common Pitfalls & Known Workarounds

1. **`voice_handler.py` is legacy** – Voice commands were intentionally removed from `bot.py`. Do not re-add voice functionality without understanding the full removal context.

2. **Slash command sync delay** – Newly added slash commands may take up to an hour to appear globally in Discord even after a successful `tree.sync()`. For faster testing, sync to a specific guild.

3. **`gpt-image-2` via Responses API does not accept `quality`, `stream`, or `response_format`** – Only pass `model`, `tools`, and `input`. See `GPTModelGenerator._generate_image_with_input_images` and `test_model_interface.py`.

4. **Thread safety for `usage_stats.json`** – Always go through `UsageTracker` methods; never read/write the JSON file directly. The internal `_lock` is per-process; do not run multiple bot instances sharing the same file.

5. **`config.py` creates directories on import** – `generated_images/` and `logs/` are created when `config.py` is first imported. This is intentional.

6. **Aspect ratios** are passed as strings (`"16:9"`, `"1:1"`, etc.) to generator methods. The Gemini SDK accepts these natively; the GPT path ignores aspect ratio for the Responses API path.

7. **Image resizing** – Input images are subject to `MAX_IMAGE_SIZE` (8 MB) and `MAX_IMAGES` (10) limits defined in `config.py`. Respect these when adding new image-processing commands.

8. **Discord embed limits** – `EMBED_DESCRIPTION_MAX_LENGTH = 4096` and `EMBED_FIELD_VALUE_MAX_LENGTH = 1024` are defined in `bot.py`. Use `split_long_message()` for long text output.

---

## Adding New Features – Checklist

- [ ] New AI-model capability → add method to `BaseModelGenerator` (abstract) and implement in both `GeminiModelGenerator` and `GPTModelGenerator`.
- [ ] New slash command → add `@bot.tree.command(...)` function in `bot.py`; call `check_usage_limit_and_respond` before doing any work; use `reserve_usage_slots` / `release_reserved_usage_slots` around generation.
- [ ] New config key → add to `.env.example` with a comment and load in `config.py`.
- [ ] New test → add a file named `test_<module>.py` and use `unittest.IsolatedAsyncioTestCase` for async tests.
