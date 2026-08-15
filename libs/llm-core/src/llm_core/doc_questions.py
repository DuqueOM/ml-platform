"""The gold set: questions this repository is actually asked, and what answers them.

**Written in the asker's vocabulary, not the document's.** This is the whole
design of the set and the reason the numbers it produces mean anything.

The plan states the case retrieval has to serve: *"the agent that knows to
search for `D-38` does not need this. The adopter who has never heard of
`D-38` does."* A gold set written by copying distinctive terms out of the
target section measures nothing — both retrievers score near-perfectly, and
the exercise reduces to confirming that `grep` works.

So each question is phrased the way someone would ask it before reading the
document that answers it: "why does my pod keep restarting" rather than
"readiness probe path", "can I just copy the folder" rather than
"`.copier-answers.yml`". Where a term is unavoidable it is one the asker would
plausibly already have (`Terraform`, `Grafana`), never one this repository
coined.

**One relevant section per question.** `evaluate_retrieval` scores against a
single index, which keeps recall unambiguous. Questions whose answer is
genuinely spread across several sections are excluded rather than assigned an
arbitrary winner — a gold label chosen by coin flip puts noise in the
measurement and calls it data.

**The labels are references, not indices.** A corpus index changes whenever a
heading is added anywhere earlier in the tree; `path#heading` survives that,
and `tests/test_doc_questions.py` fails if a label stops resolving. A gold set
that silently rots is worse than none, because it keeps producing numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    """One gold-set entry.

    Attributes:
        query: The question, in the vocabulary of someone who has not yet read
            the answer.
        answer: `path#heading` of the section that answers it.
        why: What makes this question worth measuring — the confusion it
            represents, or the failure that would follow from a wrong answer.
    """

    query: str
    answer: str
    why: str


#: Thirty questions. Small enough that every label was checked by reading the
#: section, large enough that one lucky hit moves recall by 3.3 points rather
#: than by 10.
GOLD: tuple[Question, ...] = (
    Question(
        "I just cloned this. What do I run first to check it works?",
        "QUICK_START.md#Part one — a green test suite",
        "The first question anyone asks, and the one a wrong answer wastes the most time on.",
    ),
    Question(
        "How much memory does the local setup need before I start it?",
        "QUICK_START.md#Check that it fits before creating anything",
        "Asked after something got killed, so the answer needs to arrive before that happens.",
    ),
    Question(
        "The stack came up but I do not know whether it actually works.",
        "QUICK_START.md#Assert it works, rather than that it started",
        "The distinction this repository exists to enforce, asked in the words of someone who has not learned it.",
    ),
    Question(
        "Nothing is responding and I am not sure what broke.",
        "QUICK_START.md#When it does not work",
        "Troubleshooting, phrased as frustration rather than as a symptom.",
    ),
    Question(
        "How do I shut it all down and get my machine back?",
        "QUICK_START.md#Give the memory back",
        "Cleanup. Cheap to answer, expensive to guess at.",
    ),
    Question(
        "Is this thing production ready, or is that overselling it?",
        "docs/ADOPTION.md#What this does NOT claim",
        "The question a careful evaluator asks, and the one a template is most tempted to answer dishonestly.",
    ),
    Question(
        "What do I get out of the box and what will I have to build myself?",
        "docs/ADOPTION.md#What arrives working, and what is homework",
        "The adoption decision, in its plainest form.",
    ),
    Question(
        "How do I know whether adopting this was a good idea?",
        "docs/ADOPTION.md#Whether it is working for you",
        "Asked months later. The answer is unusual enough that a retriever cannot guess it from vocabulary.",
    ),
    Question(
        "Why are some tools first class here and others just mentioned?",
        "docs/ADOPTION.md#Tool adoption is tiered, and the tier is the point",
        "The tiering is non-obvious and gets mistaken for inconsistency.",
    ),
    Question(
        "Can I just copy the example folder and rename it?",
        "docs/EXPORTING.md#Do not copy the directory",
        "The single most likely wrong move an adopter makes, asked exactly as they would ask it.",
    ),
    Question(
        "How do I pull in fixes made to the scaffolding after I generated mine?",
        "docs/EXPORTING.md#Staying up to date",
        "Upgrades. Getting this wrong destroyed a real service in the sibling repository.",
    ),
    Question(
        "I want to move one of these into its own repository. What breaks?",
        "docs/EXPORTING.md#Taking a vertical out of the monorepo",
        "Asked when a project outgrows the monorepo, which is the success case.",
    ),
    Question(
        "What does every project in here have to provide?",
        "docs/PROJECT_CONTRACT.md#The requirements",
        "The contract itself, without naming it.",
    ),
    Question(
        "One of the requirements does not apply to my problem. Am I stuck?",
        "docs/PROJECT_CONTRACT.md#Deviations",
        "The escape hatch. Undiscoverable if the answer is not found, and people quietly ignore the rule instead.",
    ),
    Question(
        "Why is there a contract instead of just letting each project do its thing?",
        "docs/PROJECT_CONTRACT.md#Why a contract at all",
        "The justification, asked sceptically — which is how it is usually asked.",
    ),
    Question(
        "A check is failing and I have no idea what it wants from me.",
        "RUNBOOK.md#When a gate fails",
        "The most common operational moment, in the words of the person having it.",
    ),
    Question(
        "Why can I not make the audit warning go away by running something?",
        "RUNBOOK.md#C7, and why you cannot clear it here",
        "The gate people most want to bypass, so the answer has to be findable at the moment they want to.",
    ),
    Question(
        "Some of these files say not to edit them. Where do they come from?",
        "RUNBOOK.md#The derived documents",
        "Derived artifacts, asked by someone who just tried to edit one.",
    ),
    Question(
        "There are green and yellow marks in a table and I cannot tell what they mean.",
        "RUNBOOK.md#How to read the status document",
        "The status document is the main artifact and its notation is not self-explanatory.",
    ),
    Question(
        "I want to add a number that blocks a bad model. Where does it go?",
        "RUNBOOK.md#Adding a threshold",
        "Thresholds, described by what they do rather than what they are called.",
    ),
    Question(
        "Does running the checks before committing cover everything the server runs?",
        "RUNBOOK.md#What `make verify` leaves out",
        "A dangerous assumption. Believing it means finding out in CI, or later.",
    ),
    Question(
        "I found a vulnerability. Who do I tell and what happens next?",
        "SECURITY.md#Reporting a vulnerability",
        "Disclosure. A wrong answer here has consequences outside the repository.",
    ),
    Question(
        "Which of these security scans actually stop a merge?",
        "SECURITY.md#Where the gaps are, stated rather than implied",
        "Advisory versus blocking. Assuming a scan blocks when it only reports is how a finding ships.",
    ),
    Question(
        "How do I cut a version of this?",
        "docs/RELEASING.md#What actually happens when you push a tag",
        "Releasing, asked without the vocabulary of the release document.",
    ),
    Question(
        "Where do I record a decision so people stop re-arguing it?",
        "docs/decisions/README.md#Format",
        "ADRs, described by their purpose rather than their acronym.",
    ),
    Question(
        "In what order should I take this on? It is a lot at once.",
        "docs/PROGRESSION.md#Stage 0 — Run the gates you did not write",
        "Sequencing. The document exists because adoption otherwise reads as all-or-nothing.",
    ),
    Question(
        "What has to exist before I can push this to a real cloud account?",
        "docs/environment-promotion.md#What has to be built before any of this runs",
        "The honest answer is a list of missing pieces, which a retriever cannot infer from optimistic vocabulary.",
    ),
    Question(
        "What is the difference between the staging and dev environments here?",
        "docs/environment-promotion.md#The four environments and what each one is for",
        "Environment purpose, routinely assumed rather than read.",
    ),
    Question(
        "Someone typed a letter into a table claiming something was verified. What stops that?",
        "VALIDATION_LOG.md#Why this file is not the status document",
        "The weakest surface in the evidence taxonomy, and the reasoning behind it is not guessable.",
    ),
    Question(
        "How do I contribute without breaking the generated files?",
        "CONTRIBUTING.md#The cadence, in this order",
        "The ordering that bites newcomers, asked as a worry rather than as a procedure.",
    ),
)
