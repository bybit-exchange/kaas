"""How far the wiki is behind the prompts that produced it (spec G5).

The wiki lags under two independent prompt sets, and a document can be behind on
either without being behind on the other:

- the extraction prompts, whose version the extraction layer records per document
  and the extraction gate compares;
- the write-phase prompts (merge-rewrite, merge-diff and the article creator's own
  system prompt), which had no version at all. Editing one invalidated nothing and
  no report named the articles it left behind.

Both are reported and neither gates. Feeding either into the composition gate
would be worse than the lag it fixes: both merge paths are additive -- merge-diff
offers only append_to_section and new_section, and merge-rewrite says nothing
about supersession -- so re-composing an article layers new content on top of the
old rather than replacing it. A prompt edit would inflate every article and pay
the whole write phase to do it. The write prompts now state how their source
blocks are ordered, which moved the write version for every existing KB without
changing that argument -- an article that exists is re-composed through the merge
paths, which are still the additive ones. write_prompt_version's own docstring
carries the full reasoning.

One function for both callers rather than a comparison in each: compile records
the versions and reports the lag it noticed while it had work to do, and kb-ai
check reports it at any time for nothing. Two copies of the predicate would have
to agree by convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WikiLag:
    """Which composed documents are behind, per gate."""

    behind_extract: list[str] = field(default_factory=list)
    behind_write: list[str] = field(default_factory=list)
    # True when at least one entry records no version for THAT gate, which is what
    # makes a large count on the first run after that version landed expected
    # rather than a defect. Per gate rather than shared: the two versions landed at
    # different times, so every KB compiled in between records one and not the
    # other -- and a single flag would caption that gate's first genuine lag as
    # expected noise and have an operator ignore it.
    extract_first_run: bool = False
    write_first_run: bool = False
    # False when that gate's prompts could not be read, so there was nothing to
    # compare against. Distinguishes "nothing is behind" from "we cannot tell";
    # reporting every document as behind would be a guess dressed as a count.
    extract_version_known: bool = True
    write_version_known: bool = True

    def summary(self) -> str:
        parts = []
        for count, known, first_run, gate in (
            (len(self.behind_extract), self.extract_version_known,
             self.extract_first_run, "extract"),
            (len(self.behind_write), self.write_version_known,
             self.write_first_run, "write"),
        ):
            if not known:
                parts.append(f"{gate} prompt version unavailable")
                continue
            parts.append(f"{count} behind the {gate} prompt"
                         + (" (first run)" if first_run else ""))
        return ", ".join(parts)


def wiki_lag(
    state: dict,
    *,
    present: set[str],
    extract_prompt_version: str,
    write_prompt_version: str,
) -> WikiLag:
    """Classify each composed document in a compile state against both gates.

    present restricts the fold to documents still under raw/: state entries are
    never garbage-collected, and a document that no longer exists cannot be behind
    its own extraction. Counting it inflates the one number an operator reads to
    decide whether a recompile is worth paying for.

    An entry with no compiled_at is skipped: no article was written from it, so
    there is nothing for the wiki to be behind on, and the composition gate
    already has it queued.

    An empty version for either gate means that gate's prompts were unreadable.
    Nothing is reported as behind for it -- a count against a version we do not
    have would be a guess dressed as a number.
    """
    behind_extract: list[str] = []
    behind_write: list[str] = []
    first_run = {"prompt_version": False, "write_prompt_version": False}

    for rel in sorted(present & state.keys()):
        entry = state[rel]
        if not entry.get("compiled_at"):
            continue

        for current, key, behind in (
            (extract_prompt_version, "prompt_version", behind_extract),
            (write_prompt_version, "write_prompt_version", behind_write),
        ):
            if not current:
                continue
            recorded = entry.get(key)
            if recorded is None:
                first_run[key] = True
            if recorded != current:
                behind.append(rel)

    return WikiLag(behind_extract=behind_extract, behind_write=behind_write,
                   extract_first_run=first_run["prompt_version"],
                   write_first_run=first_run["write_prompt_version"],
                   extract_version_known=bool(extract_prompt_version),
                   write_version_known=bool(write_prompt_version))
