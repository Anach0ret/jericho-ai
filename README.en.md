# Jericho

[![CI](https://github.com/Anach0ret/jericho-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/Anach0ret/jericho-ai/actions/workflows/ci.yml)

**A framework for assistants that act, not just answer.** The model picks an action from a set of tools; permission,
the user's "yes" and the audit log are enforced by code. An assistant is a separate project with its own skills,
settings and role; the framework is installed into it as a package.

```
request → prompt → model → tool call → checks and risk policy → action → reply → journal
```

![The assistant from the tutorial: a note is saved, deleting all notes waits for "yes", bad parameters are refused, framework checks pass](docs/media/demo.gif)

The recording (Russian assistant replies) is built by `scripts/demo_cast.py` from the tutorial code; the commands really run, with no model.

The documentation and the texts the model reads are in **Russian**; this page is a summary for English readers.
Set `language = "en"` in the project settings and the assistant answers in English: what the core says by
itself (failures, "Cancelled", the Yes/No buttons) is English, and the model is told to reply in English. "Yes" and
"no" ("okay", "go ahead", "nope"…) are understood in both languages either way.

## Why

Giving a model tools is easy. Making sure it can *do* things but cannot *wreck* things — send the wrong message,
delete in the wrong place, leak private data because a web page told it to — is the hard part. Jericho puts that
in code, not in the prompt:

- **Every tool has a risk class.** `READ` and `NAVIGATE` run right away, `CHANGE` is reversible, `EFFECT`
  (irreversible or leaves the machine) runs only after the user says "yes". The "yes" is recognised by code from
  the user's own words, not by the model; it is single-use and bound to the named object. Unattended runs
  (scheduled tasks) never perform `EFFECT` unless the project allows a tool by name.
- **Private data goes only to a trusted model.** Fields with private correspondence are not logged (crash records
  included) and by default reach only the main model; a fallback gets them only if listed in `agent.private_backends`. After private data — or after reading a local file in a phrase that also contained foreign text —
  anything that leaves the machine needs a "yes".
- **Foreign text is tracked.** Web pages, emails and program output are marked as foreign: instructions inside them
  are not commands.
- **Every call is journaled**: tool, parameters, outcome, timing, on whose behalf.
- **Skills can be written by an AI agent.** Scaffolds (`startskill`, `starttool`) and structure checks (`check`,
  E001–E016) keep the architecture from being broken silently: every rule ships with a check.

What is guaranteed, by whom and how it is tested — and what is *not* promised — is in
[docs/security.md](docs/security.md). Most importantly, this is **not a sandbox** for untrusted code: the framework
constrains the model; skill code is trusted — written or reviewed by a human.

## Use cases

- **Personal desktop assistant** — voice and text: windows, files, Telegram, tasks, memory, scheduled requests.
- **Operations assistant behind a chat bot** — server state, application log digests, explaining an error from the
  code; restarts and deploys only of what is listed in settings and only after "yes"; alerts without a model.
- **An assistant inside a service** — the service exposes its actions as tools (over its API or MCP). The user
  describes the outcome in plain words; the assistant turns it into tool calls and performs them on the user's behalf:
  reads right away, changes by the rules of the risk class, irreversible steps only after "yes" to a shown plan. For
  example, in a task tracker: "set up the tasks for the release, assign the team, split into stages" — and the result
  is in the dashboard without configuring a workflow by hand. The first two run daily; for this one the framework is
  still growing (web entry point, MCP bridge, user credentials in tools).

## Quick start

Python 3.14 and [uv](https://docs.astral.sh/uv/); Linux for now (see Status). Installed from this repository by tag
(the name `jericho` on PyPI belongs to another package).

```bash
uvx --from git+https://github.com/Anach0ret/jericho-ai@v0.64.15 jericho startproject my-assistant
cd my-assistant
git init -b main && git config core.hooksPath .githooks
uv sync && uv run pytest -q
uv run my_assistant ask "hello"      # "scripted" backend: no model, no key
```

Models: any OpenAI-compatible service (OpenRouter, Gemini, Ollama) or the Anthropic API — see
[docs/backends.md](docs/backends.md). The `claude_cli` backend uses *your own* Claude subscription and is meant for
your personal assistant only (Anthropic's terms); for anything other people use, use an API key.

## Status

0.x — young and still changing; what is public and how versions change is in [docs/stability.md](docs/stability.md).
A personal project: issues are answered when possible, no guarantees on timing.

**Platforms.** The framework is for very different assistants, and they mostly run on a server or in a container.
So there are two levels. **Development — on Linux, macOS and Windows:** create a project, write skills, services and
modules, run the assistant locally, check logic, the "yes", errors and the model, run tests. **Full safety
guarantees — Linux** (elsewhere — Linux in a container): tool deadline, stopping a program tree, private files — see
"Платформы" in [docs/security.md](docs/security.md). Linux batteries — voice, D-Bus notifications (`notify`, the
`desktop` extra), tasks on systemd timers (`tasks`) — are optional modules: leave them out on another OS and fake
them in tests. On Windows, stopping a program tree and `stop` act at once, without asking, and detached programs are not told apart.

## License

[Apache License 2.0](LICENSE).
