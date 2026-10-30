# AutoResearch Agent

A multi-agent research pipeline: give it a research question and it **reviews arXiv literature → plans an
experiment → writes and runs the code in a sandbox (fixing its own bugs) → writes a LaTeX paper → has a
reviewer agent critique it**, revising until the reviewer is satisfied.

- **LangGraph** orchestrates the agents as a state machine with explicit state handoffs.
- **FastMCP** exposes the tools (arXiv search, sandboxed Python execution, LaTeX rendering) over the
  Model Context Protocol, so any MCP client can use them too.
- **Retries** with exponential backoff on tool failures, and a **hard per-run cost cap** on LLM spend.
- A **reviewer agent** plus a deterministic **grounding check** (every number in the paper must appear in
  the real experiment output) gate the final output.
- **LangSmith** traces every agent step, LLM call and tool call; `evals/` scores runs over a fixed topic set.

Inspired by *Agent Laboratory* (Schmidgall et al., 2025, [arXiv:2501.04227](https://arxiv.org/abs/2501.04227)).

## Architecture

```
                    ┌────────────────────── LangGraph StateGraph ──────────────────────┐
  topic ──▶ START ─▶ literature ─▶ planner ─▶ engineer ──ok──▶ writer ─▶ reviewer ──accept──▶ finish ─▶ END
                                      ▲   │                    ▲            │
                                      └───┘ failed &           └─ revise ◀──┘ score < threshold
                                     attempts left                            or ungrounded numbers
                                          │ out of attempts                   (max_revisions)
                                          ▼
                                       give_up ─▶ END
                    └───────────────────────────────────────────────────────────────────┘
        each node: reads shared state ─▶ calls LLM / tools ─▶ returns only the fields it changed

  Agents ──(MCP client, retries)──▶  FastMCP server: search_arxiv · run_python · render_latex
                                                          │
                                         Docker sandbox: no network, 1 GB RAM, 1 CPU, 128 PIDs,
                                         read-only FS, non-root, timeout
```

| Agent (node) | Job | Tools |
|---|---|---|
| `literature` | Writes an arXiv query, summarizes the relevant papers | `search_arxiv` |
| `planner` | Designs one small, runnable experiment | — |
| `engineer` | Writes the experiment script, runs it, repairs it from the traceback | `run_python` |
| `writer` | Writes the LaTeX paper from the real output; fixes compile errors | `render_latex` |
| `reviewer` | Scores the paper (JSON) + automatic check for numbers not in the output | — |

## Project layout

```
autoresearch/
  graph.py        LangGraph state, agent nodes, conditional routing
  mcp_server.py   FastMCP server with the three tools (also runnable standalone)
  toolbox.py      MCP client wrapper: retries with backoff + jitter, LangSmith tool spans
  sandbox.py      Docker sandbox (and a subprocess fallback for local dev)
  llm.py          Claude client: per-run cost cap, token accounting, LangSmith LLM spans
  checks.py       Deterministic parsing + the grounding check
  prompts.py      System prompt for each agent
  runner.py       Runs one job: streams node updates, saves state, handles budget stops
evals/            Fixed topic set + scoring script
sandbox/          Dockerfile for the sandbox image
tests/            13 tests: full graph with a fake LLM, sandbox, MCP tools, retries, cost cap
main.py           CLI
config.yaml       Topic, model, limits, sandbox mode, notes
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate                # Windows: .venv\Scripts\activate
pip install -r requirements.txt
docker build -t autoresearch-sandbox:latest sandbox/   # the sandbox image (Docker must be running)

export ANTHROPIC_API_KEY=...
# optional tracing:
export LANGSMITH_TRACING=true LANGSMITH_API_KEY=... LANGSMITH_PROJECT=autoresearch-agent
```

## Usage

```bash
python main.py                                   # topic from config.yaml
python main.py --topic "Does PCA before an SVM hurt accuracy on the digits dataset?"
python -m evals.run_evals --limit 2              # run + score the eval set
python -m pytest -q                              # tests: no API key, no network, no Docker needed
python -m autoresearch.mcp_server                # serve the tools over stdio to any MCP client
```

Each run writes to `runs/<timestamp>/`: `lit_review.md`, `plan.md`, `experiment.py`,
`experiment_output.txt`, `report.tex` (+ `report.pdf` if `pdflatex` is installed), `reviews.json`, `state.json`.

## Design notes

- **Graph, not free-form agent.** Research has a natural order, so the control flow is explicit and
  testable; the LLM decides *content*, the graph decides *what runs next*. Loops (repair, revision) are
  bounded by config and by LangGraph's `recursion_limit`.
- **Tools behind MCP.** The pipeline uses the same interface an external client would. Tools can be
  reused from Claude Code/Desktop, swapped for remote servers, and tested in-memory.
- **Two kinds of failure.** A tool *error* (network blip, crash) is retried with backoff in `toolbox.py`.
  A tool *result* that says the code failed is not retried. It's fed back to the engineer as the
  observation for self-repair.
- **Sandbox is the security boundary, not the prompt.** LLM-written code runs in a container with no
  network and resource limits; API keys never enter it. The `subprocess` mode is only for local dev.
- **Cost cap is checked before every LLM call**, so a run stops cleanly with its partial state saved.
- **Don't trust the reviewer alone.** LLM judges miss made-up numbers, so a deterministic check compares
  every decimal in the paper with the experiment output and forces a revision on any mismatch.

## Limitations

- Experiments are limited to CPU-sized scikit-learn problems on built-in datasets (the sandbox has no network).
- The reviewer is an LLM grading LLM output, so scores are noisy. The eval set is small.
- Agents communicate through text code blocks (```` ```python ````, ```` ```latex ````) rather than native tool calling.
