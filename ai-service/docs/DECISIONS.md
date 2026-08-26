# Decision log

One short entry per decision. Date, decision, reason, alternative rejected.
Append; never rewrite history.

---

## 2026-08-19 — Four providers behind one adapter

**Decision.** The pipeline talks to a `ProviderAdapter`. Four implementations: `api`, `hf`,
`local`, `stub`. Selection is one environment variable.

**Reason.** The camp needs to run in three different situations — with a hosted key, with
open models, and offline on demo day — without three codebases. Building the adapter first
makes provider choice a configuration table rather than a rewrite.

**Rejected.** Hard-coding one provider and "porting later". Porting later never happens
before the deadline.

---

## 2026-08-19 — Stub is the development default

**Decision.** `PROVIDER=stub` in the test configuration and in local UI work.

**Reason.** A camper debugging a screen should not spend the budget. It also makes every
AI feature unit-testable with no network.

---

## 2026-08-19 — Skills carry evidence and a source

**Decision.** Every extracted skill records `source` (explicit | inferred) and the verbatim
`evidence` span it came from.

**Reason.** Without evidence the reviewer has to re-read the CV to trust the output, which
removes the time the feature was supposed to save. Without `source`, an inferred skill is
weighted the same as a declared one, which is wrong.

---

## 2026-08-19 — Invention guard in postprocess, not in the prompt alone

**Decision.** After the model returns, any skill whose name does not appear literally in the
document is dropped and a warning is recorded.

**Reason.** Prompt instructions reduce hallucination; they do not eliminate it. For inferred
skills, precision matters more than recall — a missing skill costs thirty seconds, an invented
one puts a false claim on a candidate's record.

---

## *(next entry)*
