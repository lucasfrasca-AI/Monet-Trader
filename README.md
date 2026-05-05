# Monet-Trader

Personal automated trading system for US equities and ETFs. Runs as
scheduled Claude Code Routines on Anthropic's cloud infrastructure;
trades through Alpaca (paper-first, live via single env var flip).

The bot is intentionally small: 4 Python modules, 6 routine prompts, 1
config file. The intelligence lives in the routine prompts and the
adversarial DeepSeek challenger that argues against every trade.

## Architecture at a glance

```
┌──────────────┐    cron      ┌──────────────────┐
│ Claude Code  │ ───────────▶ │ Routine prompt   │
│ Routines     │              │ (markdown file)  │
└──────────────┘              └────────┬─────────┘
                                       │
       ┌───────────────────────────────┼───────────────────────────┐
       ▼                               ▼                           ▼
┌──────────────┐              ┌──────────────────┐        ┌──────────────┐
│ alpaca_client│              │ deepseek_challenge│        │ risk_check   │
│ (orders,     │              │ (counter-agent)   │        │ (sizing,caps,│
│  bars, ATR)  │              └──────────────────┘        │  kill switch)│
└──────────────┘                                           └──────────────┘
       │                                                          │
       ▼                                                          ▼
┌──────────────┐                                          ┌──────────────┐
│ Alpaca API   │                                          │ memory/*.md  │
│ (paper/live) │                                          │ + git push   │
└──────────────┘                                          └──────────────┘
                                                                  │
                                                                  ▼
                                                          ┌──────────────┐
                                                          │ Discord      │
                                                          │ webhook      │
                                                          └──────────────┘
```

## Repository layout

```
Monet-Trader/
├── CLAUDE.md                operating rules; loaded every routine
├── README.md                this file
├── config.yaml              risk parameters, tickers, kill switches
├── requirements.txt         python deps
├── .env / .env.example      secrets (.env is gitignored)
├── memory/
│   ├── strategy.md          owner-editable trading rules
│   ├── portfolio.md         current state mirrored from Alpaca
│   ├── trade_log.md         append-only fill log
│   ├── research_log.md      daily theses + challenger outputs
│   └── lessons.md           weekly post-mortems
├── routines/
│   ├── pre-market.md        research only — score candidates, build plan
│   ├── market-open.md       execute plan via bracket orders
│   ├── post-open.md         30-min setup-invalidation check on new fills
│   ├── midday.md            news classifier + layered exit triggers
│   ├── close.md             end-of-horizon cap + earnings sweep
│   └── weekly-review.md     Friday post-mortem
└── scripts/
    ├── alpaca_client.py     all Alpaca trading + market-data calls
    ├── deepseek_challenge.py adversarial counter-agent
    ├── discord_notify.py    webhook poster
    └── risk_check.py        sizing, caps, kill switches
```

## Local setup (for development / dry runs)

```bash
git clone <your-fork-url> Monet-Trader
cd Monet-Trader
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy env template and fill in your 5 keys
cp .env.example .env
$EDITOR .env

# Run module self-tests
python scripts/alpaca_client.py     # account verify
python scripts/discord_notify.py    # webhook test
python scripts/deepseek_challenge.py # challenger mock thesis
python scripts/risk_check.py        # sizing + cap tests
```

## Required environment variables

| Variable | Purpose |
|---|---|
| `ALPACA_API_KEY_ID` | Alpaca account key |
| `ALPACA_SECRET_KEY` | Alpaca secret |
| `ALPACA_BASE_URL` | `https://paper-api.alpaca.markets` (paper) or `https://api.alpaca.markets` (live) |
| `DEEPSEEK_API_KEY` | DeepSeek V4 Flash for the challenger |
| `DISCORD_WEBHOOK_URL` | Single-channel webhook for embeds |

## Cloud Environment + routine setup

Once you've reviewed the scaffold and pushed to GitHub, set up the cloud
side:

1. **Push the scaffold to GitHub.**
   ```
   git add -A && git commit -m "Initial scaffold" && git push
   ```

2. **Create a Cloud Environment on claude.ai/code/routines.**
   Name it `monet-trader`. Point it at this GitHub repository.

3. **Add the 5 environment variables** from your local `.env` to the Cloud
   Environment's secrets panel. Match names exactly.

4. **Restrict network access** to the four domains the bot needs:
   - `alpaca.markets` (and subdomains: `paper-api.`, `api.`, `data.`)
   - `api.deepseek.com`
   - `discord.com`
   - `github.com` (for the trailing `git push`)

5. **Create 6 remote routines.** Each one's prompt is the contents of the
   corresponding `routines/*.md` file in this repo. Cron times are in
   UTC (EDT — US Daylight Saving); the table also shows ET (US market)
   and AEST (owner local) for sanity.

   | Routine | Cron (UTC, EDT) | Cron (UTC, EST) | ET | AEST | Prompt |
   |---|---|---|---|---|---|
   | pre-market | `0 10 * * 1-5` | `0 11 * * 1-5` | 06:00 (pre-bell) | 20:00 same day | `routines/pre-market.md` |
   | market-open | `30 13 * * 1-5` | `30 14 * * 1-5` | 09:30 (bell) | 23:30 same day | `routines/market-open.md` |
   | post-open | `0 14 * * 1-5` | `0 15 * * 1-5` | 10:00 | 00:00 next day | `routines/post-open.md` |
   | midday | `0 16 * * 1-5` | `0 17 * * 1-5` | 12:00 | 02:00 next day | `routines/midday.md` |
   | close | `55 19 * * 1-5` | `55 20 * * 1-5` | 15:55 (5min pre-close) | 05:55 next day | `routines/close.md` |
   | weekly-review | `0 20 * * 5` | `0 21 * * 5` | 16:00 Fri | 06:00 Sat | `routines/weekly-review.md` |

   *(US DST flips ~mid-March and early-November; switch the cron column
   twice yearly. AEST never observes DST.)*

6. **In each routine's permissions, enable "Allow unrestricted branch
   pushes."** The routines commit + push state at the end of every run.

7. **Manual smoke test.** Run `pre-market` via "Run now" before the next
   scheduled fire. Verify the Discord channel receives the brief and the
   repo receives a fresh commit on the default branch.

8. **Validate the dry run.** Open `memory/research_log.md` after the run.
   The candidate list should be present, with each ticker's challenger
   output verbatim. If anything looks wrong, fix it before letting the
   automatic schedule fire.

9. **Let it run on schedule.** Monitor Discord each morning AEST. Adjust
   `memory/strategy.md` between runs as patterns emerge in
   `memory/lessons.md`.

## Switching paper → live

After 4–6 weeks of validated paper performance:

1. Update `ALPACA_BASE_URL` in the Cloud Environment to
   `https://api.alpaca.markets`.
2. Confirm your Alpaca live account is funded with the intended USD 500–1000.
3. Run the **pre-market** routine manually and verify it reports against
   the live account (equity should match your live cash).
4. Resume scheduled runs.

There is **no other change** required. No code edits, no config flips.
This is enforced by `CLAUDE.md` Rule 2.

## Disclaimer

Research-grade automation for personal use. Not financial advice. The
owner is responsible for all decisions and outcomes.
