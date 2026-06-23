# PRISM Compliance Plan — Discord Developer Policy

## Context

Baxi PRISM stores a persistent, cross-server behavioral **trust score** per user, a per-user
**event dossier**, and **LLM-generated summaries of individuals**. The Discord Developer Policy
forbids exactly this:

- "Do not use API Data to: **profile Discord users, their identities, or relationships with
  other users**"
- "Do not use API Data for any purpose **outside of what is necessary to provide your stated
  functionality**"
- Aggregated use is allowed only if data "has been **aggregated or de-identified** such that it
  cannot be associated with, or used to identify, any individual"
- "**Obtain consent**... respect user decisions to opt out"

Per-guild moderation (warnings, this-server flags, mod actions) is fine — every mod bot does it.
The violation is specifically: (1) a durable cross-guild per-user score, (2) the per-user event
history aggregated across servers, (3) LLM summaries describing individuals, (4) silent scanning
beyond stated functionality.

Goal: keep the *useful* protection (catch risky joins, spam, raids) while removing anything that
constitutes cross-server profiling of identifiable individuals.

## Design principles (compliant)

1. **Per-guild by default.** Moderation data lives in the guild that produced it. No network-wide
   per-user behavioral profile.
2. **Compute risk live, don't store a dossier.** Risk at decision time is derived from data Discord
   already exposes (account age, join recency, the current message) plus *that guild's own* recent
   moderation actions. Nothing persistent that "profiles" the user.
3. **No LLM summaries of individuals.** Remove `prism_useranalyst` entirely.
4. **Cross-server only as an opt-in safety denylist of concrete actions** — never inferred scores.
   See decision below.
5. **Consent + transparency + deletion.** Honor opt-out (exists), add a privacy disclosure, support
   data export/delete on request, auto-expire stored data.

## Chosen model — human-gated minimal denylist (Option B, refined)

The line that keeps us compliant: **what crosses servers must come from a human moderator decision,
never from the bot's own behavioral inference, and must carry no behavioral detail.**

| Data | Stored? | Scope | Source |
|------|---------|-------|--------|
| Trust score / "what exactly they did" (spam counts, message content, event log) | **Never** | — | — |
| Behavioral detection (spam, chatfilter hits) | Yes, **per-guild, live/ephemeral** | this guild only | bot (automated) |
| "User is flagged" cross-server | Yes, **minimal** `{user_id, category, flagged_by_guild, timestamp}` | network, opt-in | **human mod only** |

- **Behavior (spam, filter) stays per-guild and live.** The bot detecting spam acts locally and may
  set a *local* flag, but this NEVER auto-propagates to a cross-server record. Auto cross-server
  behavioral flagging = the forbidden profiling, so it is not done.
- **Cross-server flag is human-gated.** It is written only when a moderator takes a concrete action
  (ban, or an explicit "report to network" button). Stored fields are minimal: the user id, a **coarse
  category** (e.g. `raid` / `spam` / `hate` / `other`) chosen by the mod, the reporting guild, and a
  timestamp. No score, no event history, no message content, no "what exactly". This is the
  "nur dass er auffällig ist, nicht was genau" requirement.
- **Opt-in consumption.** Each guild decides whether to consume the network denylist
  (`safety_denylist_enabled`). A hit produces an alert / review-queue item, not an automatic punishment
  unless the guild configures one.
- **Raid coverage.** A spammer hitting many servers is caught once a human bans them anywhere; fresh
  throwaway-account raids are caught by the live account-age signal without any stored data.

This is framed as abuse/safety prevention (a moderation bot's stated functionality), stores a human
moderator's labeled fact rather than an inferred profile, and is deletable + opt-out respecting.

## Concrete changes

### Remove (the clear violations)
- **Stored trust score + score math.** Delete `score`, `calculate_score`, recovery/velocity/decay
  logic from `assets/trust.py`. Risk becomes a live, ephemeral computation, not a saved number.
- **Cross-guild event dossier.** Stop writing a per-user `trust_event` log aggregated across guilds.
  Mod events already live per-guild in `mod_events` — that's enough.
- **LLM user summaries.** Remove `prism_useranalyst` model calls, `llm_summary*` fields, the summary
  batch in `TrustScoreTask` (`assets/trust.py` LLM section, `assets/tasks.py`).
- **Silent scanning.** When chatfilter is OFF, do not run the model just to record PRISM data
  (`assets/events.py` silent-scan branch). Only act within stated functionality.
- **Auto-flag based on score.** No algorithmic network flag. Replace with the denylist (Option B) or
  per-guild flags only.

### Replace with
- **`assets/moderation/risk.py` (new) — live, stateless risk signals.** A function
  `assess(member, guild) -> RiskAssessment` returning *non-persistent* signals computed on the fly:
  - account age (`member.created_at`) — from Discord, not stored
  - join recency
  - this guild's active warnings / recent mod actions for the user (per-guild `warnings`, `mod_events`)
  - membership on the opt-in safety denylist (Option B), if enabled
  No score is saved; the assessment is used for the on-join alert and adaptive strictness, then
  discarded. `RiskContext` (in `assets/moderation/context.py`) reads from this instead of `sentinel`.
- **Human-gated safety denylist.** Reuse the existing global ban concept (`global_bans` / `ba_ban` in
  `assets/repo/global_store.py`) rather than inventing new storage. Entry = `{user_id, category,
  flagged_by_guild, timestamp}` written ONLY when a human mod bans the user or clicks an explicit
  "report to network" action; `category` is a coarse mod-chosen label (raid/spam/hate/other). Never
  populated by automated detection. Per-guild toggle `safety_denylist_enabled` to consume it; a hit
  raises an alert / review item, not an automatic punishment. Entries are deletable on request.

### Keep (already compliant)
- Per-guild chatfilter, antispam, warnings, mod-gate alerts, review queue, self-training classifier.
  The new moderation **engine, RiskContext, Verdict, enforce, gate, learning** all stay — only their
  data source changes from "stored cross-guild score" to "live per-guild signals".
- Mod-gate on-join alert: now driven by live signals (account age + this guild's history + opt-in
  denylist) instead of a stored network score. Same UX, compliant source.

### Data layer
- Drop tables `trust_profiles`, `trust_event` (`assets/db.py`), their repo (`assets/repo/standalone.py`),
  and the `prism_enabled` plumbing that gated cross-guild recording. Keep per-guild `users` flags.
- Migration: a one-time script to **delete** existing `trust_profiles`/`trust_event` data (we are
  removing profiles, so deletion is the migration). Preserve any concrete bans into the denylist.

### Consent / transparency / deletion
- Add a **privacy disclosure** (what per-guild data is stored, retention, how to opt out / request
  deletion) — link from the dashboard and a `/privacy` command.
- Honor existing **opt-out** (`set_opt_out`) for the denylist consumption too.
- Add **data export + delete on request** (per-guild warnings/flags/mod events for a given user).
- **Retention:** per-guild mod data already auto-prunes at 90 days (`mod_events`, `filter_events`) —
  document it; apply the same to any retained denylist entries (or keep bans until lifted).

## Rename / framing
Consider retiring the "PRISM trust score" branding (it reads as surveillance). Frame the feature as
**per-server moderation assistance + opt-in raid/abuse safety list** in user-facing copy.

## Critical files
- `assets/trust.py` — strip score/dossier/LLM; keep only thin helpers or remove module.
- `assets/moderation/risk.py` (new), `assets/moderation/context.py` — live signal source.
- `assets/events.py` — remove silent-scan; risk via live signals.
- `assets/tasks.py` — remove `TrustScoreTask` recalc + LLM batch; (denylist needs no recalc).
- `assets/db.py`, `assets/repo/standalone.py`, `assets/repo/global_store.py` — drop profile tables,
  reuse ban list for denylist.
- `assets/dash/*` — replace PRISM score UI with per-guild risk + denylist toggle + privacy link.

## Verification
1. Grep confirms no code path writes a per-user cross-guild score or an LLM user summary.
2. On-join alert still fires for new account / opt-in-denylisted user (live signals), no stored score.
3. Existing `trust_profiles`/`trust_event` data is wiped by migration; bot boots clean.
4. Privacy disclosure reachable; opt-out + delete-on-request work end to end.

## Open question for you
Option A (fully per-guild) or Option B (per-guild + opt-in safety denylist)? Recommendation: B.
