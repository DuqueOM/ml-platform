# Security baselines

CI runs **three** of the four scanners below over this repository's
infrastructure and dependencies (`.github/workflows/ci.yml`, jobs `IaC and
Kubernetes security` and `Supply chain`). tfsec is not among them, and the
table says so — this sentence said "four" until an audit read it against its
own table, which is the smallest possible version of the defect these files
exist to prevent. Until this directory existed there was nowhere to record that
a finding had been looked at and accepted, so the only way to get a scanner to
stop reporting something was to weaken the scanner — in a workflow argument,
where the decision is invisible and permanent.

That is the gap these files close. They are where an accepted finding is
written down, with the reason and the date it stops being accepted.

| Tool | Baseline file | Holds |
| --- | --- | --- |
| Checkov | `checkov.yml` | `skip-check` entries (Terraform + Kubernetes) |
| tfsec | `tfsec.yml` | `exclude` entries — see the file, tfsec is not in CI |
| Trivy | `.trivyignore` | CVE IDs and misconfiguration IDs, one per line |
| Kubescape | none | Kubescape has no baseline file; see below |

## There are no suppressions in any of these files

Every file in this directory is empty of entries, and that is deliberate.
Pre-populating a baseline with suppressions inherited from another repository
means the first person to read it is reading exceptions for findings that never
occurred here — which is how a suppression list becomes a place nobody reads
before adding one more.

The upstream template this repository borrows from carries three tfsec
exclusions. Running the equivalent checks here showed that copying them over
would have been actively wrong; the evidence is recorded in `tfsec.yml`.

## What an entry must carry

Four things, all of them, on every entry:

1. **The finding ID** exactly as the tool reports it (`CKV_GCP_20`,
   `CVE-2026-12345`, `GCP-0061`). Never a wildcard, never a whole rule family.
2. **The reason** it is accepted rather than fixed. "Fixing it is work" is not
   a reason. A vendor CVE with no patched release, a check the repository
   satisfies through a control the scanner cannot see, or a scan-scope artifact
   are reasons — and the third one needs the evidence written next to it.
3. **An owner**, as a GitHub handle. Not a team, not a role. A person to ask.
4. **An expiry date**, `YYYY-MM-DD`, no more than one quarter out.

Written as a comment directly above or beside the entry:

```text
# expiry: 2026-11-13  owner: @handle
# reason: <why this cannot be fixed now, and what would make it fixable>
```

## An expired entry is a finding in itself

Not a warning, not a nag — a finding, with the same standing as the one it
suppresses. Reaching the expiry date means the acceptance was never revisited,
and an unrevisited acceptance is indistinguishable from an unnoticed one. The
resolution is to fix the underlying issue, or to write a fresh justification
with a fresh date and a fresh look at whether the reason still holds.

Extending an expiry is a decision. It should cost a minute of thought and leave
a trace in the diff. That is the entire mechanism.

## A suppression with no expiry is a decision nobody made on purpose

Someone silenced a scanner under deadline pressure and moved on. The entry then
outlives the deadline, the release, and usually the person — and every reader
after that assumes it was considered, because it is written down. Permanence is
what makes a suppression dangerous, not the suppression itself.

If an entry genuinely should be permanent, that is not a baseline entry. It is
a check that does not apply to this repository, and it belongs in the scanner's
configuration with the reasoning next to it, reviewed like any other config.

## Scope every entry as narrowly as the tool allows

Suppress the finding, not the rule. A rule that fires once today fires on new
code tomorrow, and a bare rule ID in this directory silences both.

This is not hypothetical here. `GCP-0061` (master authorized networks on GKE)
fires twice in this repository: once on `platform/terraform/gcp/main.tf`, where
the setting is genuinely absent, and once on
`services/demand-forecast-serving/infra/terraform/gcp/compute.tf`, where it is
present as a `dynamic` block the scanner does not evaluate. One rule ID, one
false positive, one real gap. Excluding the ID would have silenced the real gap
to quiet the false one.

Where the tool supports it, prefer an inline annotation at the resource
(`# checkov:skip=CKV_GCP_20:reason`) over a repository-wide entry, and list it
here too so there is one place to review.

## Removing an entry

Delete it. CI enforces the finding again on the next run, which is the point.
No ceremony, no tracking issue to close first — the fix landing is the signal.

## Kubescape

Kubescape has no baseline file in this directory because it has no ignore-file
mechanism worth wiring up; exceptions are declared in a JSON object passed to
the scan. It also runs `continue-on-error: true` in CI, so it reports without
blocking and nothing needs suppressing yet. If it is ever promoted to blocking,
the exceptions object belongs here, under the same four rules above.

## Wiring

These files live outside the working directory Checkov and Trivy search by
default, so each needs an explicit flag (`--config-file`, `--ignorefile`).
**One is already wired**, and knowing which is the difference between a
suppression that takes effect and one that does not:

| File | Wired | Where |
| --- | --- | --- |
| `.trivyignore` | **yes** | `.github/workflows/ci.yml` — `trivyignores:` |
| `checkov.yml` | no | needs `--config-file` |
| `tfsec.yml` | no | needs `--config-file` |

This paragraph previously said *"none of these files are read
automatically"*, which was true when it was written and stopped being true
when Trivy was wired. QA-4 round four found it. The wrong direction is the
dangerous one: a reader believing a `.trivyignore` entry is inert would add
one without the scrutiny a live suppression deserves.

For the unwired two, an empty baseline and an unread baseline behave
identically — so wire each in the same change that adds its first entry, and
update the table in that change. `scripts/check_baselines_expiry.py` reads
all three regardless of wiring, because an entry that has not taken effect
yet still has to carry its owner and its expiry.
