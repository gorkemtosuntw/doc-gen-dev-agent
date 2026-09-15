# doc-gen-dev-agent

An AI developer agent that turns Trello cards into code and pull requests automatically.

When the bot user is added as a member to a Trello card, the agent kicks in: it clones the target repository, passes the card description to an LLM as a task, applies the returned code change, and opens a pull request on GitHub. Along the way it moves the card between lists and comments on it.

## How it works

```
Bot is added to a Trello card
        ↓
POST /webhook  (FastAPI)
        ↓
Card is moved to the "In Progress" list
        ↓
Target repo is cloned into a temporary workspace → feature/ticket-XXXXX branch
        ↓
AI agent inspects the repo (read_file tool) and produces a SEARCH/REPLACE block
        ↓
Patch is applied to the file → commit → push
        ↓
Pull request is opened on GitHub
        ↓
PR link is added as a card comment → card is moved to the "Review" list
```

If anything fails or the patch cannot be applied, a warning comment is added to the card and the workspace is cleaned up.

## Project structure

```
app/
├── main.py                     # FastAPI application, /webhook endpoint
├── config.py                   # Environment variables and constants (repo name, Trello list IDs)
├── core/
│   └── orchestrator.py         # Main pipeline: clone → AI → patch → commit → push → PR
├── services/
│   ├── ai_agent.py             # OpenAI call, tool-calling loop, prompt
│   ├── trello_service.py       # Trello REST API (move card, comment, fetch card details)
│   └── git_service.py          # (currently empty, reserved for git helpers)
└── utils/
    └── file_ops.py             # File listing/reading and SEARCH/REPLACE patch application
```

## Setup

```bash
git clone https://github.com/gorkemtosuntw/doc-gen-dev-agent.git
cd doc-gen-dev-agent

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
pip install openai              # missing from requirements.txt
```

### Environment variables

Create a `.env` file in the project root:

```env
TRELLO_API_KEY=...
TRELLO_TOKEN=...
GITHUB_TOKEN=...
OPENAI_API_KEY=...
```

Update the following values in `app/config.py` to match your own setup:

| Setting | Description |
| --- | --- |
| `GITHUB_REPO_NAME` | The target repository the agent works on (`owner/repo`) |
| `LIST_IN_PROGRESS` | Trello list ID the card is moved to when work starts |
| `LIST_REVIEW` | Trello list ID the card is moved to after the PR is opened |
| `BOT_USERNAME` | Trello username that triggers the pipeline when added to a card |

### Running

```bash
uvicorn app.main:app --reload
```

The service needs to be reachable from the outside (use a tunnel such as ngrok during local development). Then register that address, with the `/webhook` path, as a webhook for your board:

```bash
curl -X POST "https://api.trello.com/1/webhooks/" \
  -d "key=$TRELLO_API_KEY" \
  -d "token=$TRELLO_TOKEN" \
  -d "callbackURL=https://<your-address>/webhook" \
  -d "idModel=<board_id>"
```

Trello sends a `HEAD` request to the address before registering the webhook; the application already handles it.

## Usage

1. Create a card in Trello.
2. Put the task in the card **title** and the details in the **description** — both go straight to the LLM as the task. Naming the file to be changed improves the success rate considerably.
3. Add the `BOT_USERNAME` user as a member of the card.
4. The card moves to "In Progress"; within a few minutes you either get a PR link as a comment or an error message.

An example card:

> **Title:** Add a timestamp field to the GenerateRequest interface
> **Description:** Add a `timestamp` field of type `string` to the `GenerateRequest` interface in `common/types.ts`.

## Technical notes

- **Patch format:** The agent is expected to return output that starts with a `FILE: <path>` line and contains `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` blocks. If the search block is not found verbatim in the file, a whitespace-stripped version is tried; if that fails too, the patch is not applied.
- **Tool calling:** The agent runs for at most 3 turns and can read repository files via the `read_file` tool during those turns. If it cannot produce a valid patch, the pipeline ends without one.
- **Scope:** A single file is modified per run (the first `FILE:` line in the response).
- **Model:** `gpt-4o`, hardcoded in `app/services/ai_agent.py`.
- **Workspace:** Each task is cloned in isolation under `workspace/<uuid>/` and deleted when the run finishes.

## Known gaps

- The `openai` package is missing from `requirements.txt`.
- `app/services/git_service.py` is empty; git operations currently live in the orchestrator.
- Configuration is hardcoded in `config.py` and could move to environment variables.
- No webhook verification (Trello signature check) is performed.
- Generated PRs require human review; there is no auto-merge.
