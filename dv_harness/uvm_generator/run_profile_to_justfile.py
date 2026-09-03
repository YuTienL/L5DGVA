"""Generate a `justfile` from a validated run_profile.json.

Purpose (per the asset-processing design in docs/RUN_PROFILE.md): the
generated justfile is the ONLY execution surface an agent may call for this
environment. Every recipe forwards to `make` using exactly the variable
names captured in run_profile.json -- never a hand-composed vcs/simv command
line -- and every recipe validates its arguments against the profile's own
enum/retired constraints BEFORE shelling out, so an invalid combination
fails fast with the source Makefile's own $(error) text instead of vcs
failing deep, or a knob being silently ignored.

A modeled recipe missing an option an agent believes it needs is a
question-queue item, not a reason to hand-edit this file or fall back to
`make` directly. As of 2026-09-04 that is a real code path rather than only
this comment: `assert_option_modeled()` refuses the option and
`build_missing_option_question_queue_entry()` asks it through the SAME
`question_queue.QuestionQueueStore` `connectivity.build_t4_question_queue_
entry()` uses. The one sanctioned human-only escape hatch,
`human_raw_override`, now demands an explicit acknowledgment token
(`HUMAN_OVERRIDE_ACK_TOKEN`) instead of being restricted by a comment.

And because the knob worth smuggling in is in the PROFILE rather than in the
generated justfile, `verify_source_authority()` re-reads the real Makefile /
reference command.txt before generating anything and refuses a profile whose
params do not trace back to it -- the enforced form of "the reference source
is the highest authority", which the schema previously only asserted in
prose.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from dv_harness.uvm_generator.run_profile import (
    RunProfileValidationError,
    assert_params_traceable_to_source,
    assert_source_unchanged,
    check_constraints,
    find_param,
    load_run_profile,
)

#: Every missing-option question is asked in the `env` domain -- this is a
#: question about the ENVIRONMENT's own build/run surface, not about VIP
#: behaviour or DUT design, and `question_queue.route_owner()` routes it to
#: the DV-owner accordingly. Named here rather than passed by callers so the
#: routing cannot drift per call site.
MISSING_OPTION_QUESTION_DOMAIN = "env"

#: The literal token the generated `human_raw_override` recipe demands as its
#: first argument. Spelled as a first-person human claim so it cannot be
#: mistaken for a flag, and so its appearance in a CI log or shell history is
#: legible as what it is.
HUMAN_OVERRIDE_ACK_TOKEN = "I-AM-A-HUMAN-BYPASSING-RUN-PROFILE"

#: A missing execution knob decides how the DUT is BUILT or RUN (a compile
#: define, a plusarg, a testname). Getting it wrong does not produce a
#: visibly broken run -- it produces a run that passes while verifying
#: something other than what was intended. So this is `affects_pass_fail_
#: verdict: True`, exactly as `connectivity.T4_QUESTION_CONTEXT` is for an
#: undecidable bind, which pushes it to Tier 3 (CANNOT_ASSUME).
MISSING_OPTION_QUESTION_CONTEXT: dict = {"affects_pass_fail_verdict": True}


class UnmodeledOptionError(RunProfileValidationError):
    """An option an agent wants is not in the authoritative source's profile.

    A subclass of RunProfileValidationError so existing fail-closed handling
    of an invalid profile also catches this, while a caller that wants to
    route the question rather than abort can catch it specifically."""


def missing_option_context_path(target: str, option: str) -> str:
    """The stable evidence path one missing-option question is anchored to.
    `question_queue.make_question_key()` hashes this, so the SAME missing
    option on the SAME target always mints the SAME Q-ID however many times
    generation is re-run -- the same repeat-question-rate=0 property
    `connectivity.scoreboard_field_context_path()` exists to preserve."""
    return f"run_profile/targets/{target}/params/{option}"


def assert_option_modeled(profile: dict, target: str, option: str) -> dict:
    """Raise UnmodeledOptionError unless `option` is a real param of the
    authoritative source. Returns the param definition when it is.

    This is the code form of the rule this module's docstring has always
    stated in prose: a modeled recipe missing an option an agent believes it
    needs is a question-queue item, not a reason to add the knob. Before
    2026-09-04 nothing in `dv_harness/uvm_generator/` referenced the question
    queue at all -- the instruction existed only as this file's own comments
    and the generated justfile's banner, both of which an agent editing
    run_profile.json is by definition not being stopped by."""
    param = find_param(profile, option)
    if param is None:
        raise UnmodeledOptionError(
            f"UNMODELED_OPTION: {option!r} is not a param of "
            f"{profile.get('source', {}).get('path')!r}, the authoritative source for target "
            f"{target!r}. Route it via build_missing_option_question_queue_entry(); do not add "
            "it to run_profile.json and regenerate."
        )
    return param


def build_missing_option_question_queue_entry(
    store, *, profile: dict, target: str, option: str, options: list,
    recommendation: str, assumption_if_unanswered: str,
    context: dict | None = None, now=None,
) -> dict:
    """Ask, through the REAL question queue, for an execution option the
    authoritative source does not model.

    Deliberately the same shape and the same store as
    `connectivity.build_t4_question_queue_entry()` -- one question queue for
    this harness, not a second parallel one for execution options. The
    returned record is that store's own persisted, schema-validated
    question: its `id` is DERIVED by `question_queue.make_question_id()`, its
    `owner` by `route_owner()`, its `tier`/`blocking` by `classify_tier()`.

    `options` must be a real pre-researched 2-3 item list, enforced as a hard
    length check -- an open-ended "what should we do?" is not a queue item,
    it is a shrug. `recommendation` must be one of those labels."""
    from dv_harness import question_queue  # local import: keeps this module
                                            # importable without the queue's deps

    if isinstance(store, (str, Path)):
        store = question_queue.QuestionQueueStore(Path(store))
    if find_param(profile, option) is not None:
        raise RunProfileValidationError(
            f"OPTION_ALREADY_MODELED: {option!r} IS a param of the authoritative source; invoke "
            "it through the generated recipe rather than asking whether it should exist."
        )
    if not (2 <= len(options) <= 3):
        raise RunProfileValidationError(
            f"OPTIONS_MUST_BE_PRE_RESEARCHED_2_TO_3: got {len(options)} for {option!r}"
        )
    normalized = [o if isinstance(o, dict) else {"label": str(o)} for o in options]
    labels = [o.get("label") for o in normalized]
    if recommendation not in labels:
        raise RunProfileValidationError(
            f"RECOMMENDATION_MUST_BE_ONE_OF_OPTIONS: {recommendation!r} not in {labels}"
        )

    merged_context = dict(MISSING_OPTION_QUESTION_CONTEXT)
    merged_context.update(context or {})
    source_path = (profile.get("source") or {}).get("path")
    return store.add_question(
        domain=MISSING_OPTION_QUESTION_DOMAIN,
        question=(
            f"Target {target!r} needs option {option!r}, which {source_path!r} does not define. "
            "Should the authoritative source gain this knob, or is an existing modeled param the "
            "right way to express it?"
        ),
        context_path=missing_option_context_path(target, option),
        options=normalized, recommendation=recommendation,
        assumption_if_unanswered=assumption_if_unanswered,
        context=merged_context, now=now,
    )

_STANDALONE_VALIDATOR_TEMPLATE = (
    Path(__file__).resolve().parent / "templates" / "sim_scripts" / "validate_run_profile_args.py"
)

# Targets this generator knows how to build a real recipe for. Any other
# target present in the profile's `targets` list still gets a bare
# passthrough recipe (no typed params, no validation) -- present because it
# is real, not because this generator understands it.
_MODELED_TARGETS = {"compile", "sim", "regress", "check", "clean", "distclean", "list_patterns", "help"}


def _param_summary(profile: dict, name: str) -> str:
    """One-line 'NAME (=default, enum: a|b|c)' summary for the comment above
    a recipe -- documentation only, never interpolated into the recipe body.
    Real defaults stay owned by the source Makefile's own `?=`; duplicating
    them as just parameter defaults was tried and rejected (see the design
    note on `*args` passthrough below) because just recipe parameters are
    POSITIONAL, not KEY=value, which silently mismatches make's own
    KEY=value convention -- confirmed by a real `just --dry-run` run
    producing `SPEED=speed=gen1` instead of `SPEED=gen1`.
    """
    param = find_param(profile, name)
    if not param:
        return name
    bits = [name]
    if param.get("default") not in (None, ""):
        bits.append(f"={param['default']}")
    if param.get("type") == "enum" and param.get("enum"):
        bits.append(f" [{'|'.join(param['enum'])}]")
    return "".join(bits)


def generate_justfile(profile: dict) -> str:
    source = profile["source"]
    lines: list[str] = []
    lines.append("# AUTO-GENERATED by dv_harness.uvm_generator.run_profile_to_justfile")
    lines.append(f"# Source of truth: {source['path']}")
    if source.get("content_sha256"):
        lines.append(f"# Source sha256 at extraction time: {source['content_sha256']}")
    lines.append(
        "# DO NOT hand-edit the recipes below. Re-run the extractor against the real "
        "source and regenerate this file. An agent that wants a knob not listed here "
        "must raise it via the question queue -- it may never add one itself."
    )
    lines.append("")
    lines.append('set shell := ["bash", "-uc"]')
    lines.append("")
    lines.append('_profile := "run_profile.json"')
    lines.append("")
    lines.append(
        "# Validates one target's args against run_profile.json's own enum/retired "
        "constraints before make ever runs. Fails fast with the source's own $(error) "
        "message rather than letting an invalid combination reach vcs. Deliberately a "
        "standalone stdlib-only script, not `python3 -m dv_harness...` -- this "
        "environment ships to a DV team that does not necessarily have the Harness "
        "package installed alongside it. Plain relative paths, not "
        "{{justfile_directory()}} -- interpolating an absolute Windows path through "
        "`set shell := [\"bash\", \"-uc\"]` mangles the backslashes (confirmed by a real "
        "run); this justfile is always invoked from its own directory like every other "
        "recipe here that references run_profile.json the same way."
    )
    lines.append("_validate target *args:")
    lines.append('\t@python3 validate_run_profile_args.py {{_profile}} {{target}} {{args}}')
    lines.append("")

    for target in profile.get("targets", []):
        name = target["name"]
        if name not in _MODELED_TARGETS:
            continue
        desc = target.get("description", "")
        params: list[str] = target.get("params", [])
        recipe_name = name.replace("_", "-")

        if desc:
            lines.append(f"# {desc}")
        if target.get("requires_rebuild"):
            lines.append("# Changing any variable below requires a rebuild (this target itself IS the rebuild).")

        if not params:
            lines.append(f"{recipe_name}:")
            lines.append(f"\tmake {name}")
            lines.append("")
            continue

        # *args (variadic passthrough), NOT typed named parameters: just
        # recipe parameters are positional, so `just compile speed=gen1`
        # would bind the ENTIRE literal token "speed=gen1" to just's first
        # positional parameter rather than reading it as KEY=value the way
        # `make compile SPEED=gen1` does -- confirmed by a real
        # `just --dry-run` run before this design was adopted. Passthrough
        # keeps the real Makefile variable names as the actual interface,
        # keeps defaults owned by the Makefile's own `?=` (never duplicated
        # here), and still restricts an agent to real make VAR=value pairs
        # for a real, allow-listed target -- it can never invoke an
        # unmodeled make target this way, only unmodeled variables on a
        # modeled one, which _validate still catches for anything with a
        # known constraint.
        var_summary = "  ".join(_param_summary(profile, p) for p in params)
        lines.append(f"# vars: {var_summary}")
        lines.append(f"{recipe_name} *args:")
        lines.append(f"\t@just _validate {name} {{{{args}}}}")
        lines.append(f"\tmake {name} {{{{args}}}}")
        lines.append("")

    lines.append(
        "# HUMAN OVERRIDE ONLY. An agent calling this instead of a modeled recipe above "
        "is bypassing the reason run_profile.json exists. If a modeled recipe is missing "
        "a real option, that is a question-queue item, never a reason to use this."
    )
    lines.append(
        "# The `ack` parameter is a real gate, not ceremony: until 2026-09-04 this recipe "
        "was restricted by the comment above and nothing else, so it was indistinguishable "
        "from a modeled recipe at the point of invocation. Requiring the literal token "
        f"below means the bypass cannot happen by reflex or by tab-completion, and it "
        "appears verbatim in shell history and CI logs as an attributable claim. HONEST "
        "RESIDUAL: an agent CAN type this token. What is closed is silent, deniable bypass; "
        "what is not closed, and cannot be from inside a justfile, is a deliberate one."
    )
    lines.append(f'human_raw_override ack target *args:')
    lines.append(
        f'\t@[ "{{{{ack}}}}" = "{HUMAN_OVERRIDE_ACK_TOKEN}" ] || '
        f'{{ echo "refusing: human_raw_override requires the literal first argument '
        f'{HUMAN_OVERRIDE_ACK_TOKEN}. An agent that wants an unmodeled option must raise it '
        f'via the question queue (run_profile_to_justfile.build_missing_option_question_queue_entry), '
        f'not bypass run_profile.json." >&2; exit 1; }}'
    )
    lines.append("\tmake {{target}} {{args}}")
    lines.append("")

    return "\n".join(lines) + "\n"


def copy_standalone_validator(out_dir: Path) -> Path:
    """Copy the dependency-free validator script next to a generated
    justfile. Must be called whenever a justfile is generated for a real
    (non-scratch) environment -- the `_validate` recipe references this
    file by relative path and has no fallback.
    """
    dest = out_dir / _STANDALONE_VALIDATOR_TEMPLATE.name
    shutil.copyfile(_STANDALONE_VALIDATOR_TEMPLATE, dest)
    return dest


def resolve_source_path(profile: dict, profile_path: Path) -> Path | None:
    """The real authoritative source file this profile claims to describe,
    resolved relative to the profile's own directory (`source.path` is
    documented as relative to the environment root, and run_profile.json
    lives at that root). Returns None when it is not present on disk --
    which is a real and common case (a profile inspected away from its
    environment), and is reported as NOT_AVAILABLE rather than guessed at."""
    raw = (profile.get("source") or {}).get("path")
    if not raw:
        return None
    candidate = Path(profile_path).resolve().parent / raw
    return candidate if candidate.is_file() else None


def verify_source_authority(profile: dict, profile_path: Path) -> dict:
    """Confirm this profile is still derivable from its real source before
    anything is generated from it. Two independent checks, both against the
    file rather than against the profile's own claims: the recorded content
    hash still matches, and every param name still appears as a token in it.

    Returns a status dict; raises RunProfileValidationError on a real
    violation. `status: "NOT_AVAILABLE"` when the source file is not on disk
    -- generation still proceeds, because refusing to generate a justfile
    away from its environment would be a false positive that gets this check
    routed around, and the profile itself was already schema-validated."""
    source_path = resolve_source_path(profile, profile_path)
    if source_path is None:
        return {"status": "NOT_AVAILABLE",
                "reason": "the authoritative source file named in source.path is not present "
                          "next to this run_profile.json, so it cannot be re-read to verify "
                          "the profile against it"}
    assert_source_unchanged(profile, source_path)
    assert_params_traceable_to_source(profile, source_path.read_text(encoding="utf-8",
                                                                     errors="replace"))
    return {"status": "VERIFIED", "source": str(source_path)}


def generate_and_write(profile_path: Path, out_path: Path, copy_validator: bool = True,
                       verify_source: bool = True) -> str:
    profile = load_run_profile(profile_path)
    if verify_source:
        verify_source_authority(profile, Path(profile_path))
    text = generate_justfile(profile)
    out_path.write_text(text, encoding="utf-8")
    if copy_validator:
        copy_standalone_validator(out_path.parent)
    return text


def _cli_validate(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: validate <run_profile.json> <target> [KEY=VALUE ...]", file=sys.stderr)
        return 2
    profile_path, target = argv[0], argv[1]
    kv_args = argv[2:]
    values: dict[str, str] = {}
    for arg in kv_args:
        if "=" not in arg:
            continue
        key, _, val = arg.partition("=")
        if val != "":
            values[key] = val

    try:
        profile = load_run_profile(Path(profile_path))
    except RunProfileValidationError as exc:
        print(f"run_profile.json is invalid, refusing to validate against it:\n{exc}", file=sys.stderr)
        return 2

    violations = check_constraints(profile, values)

    for constraint in profile.get("constraints", []):
        if constraint["kind"] != "retired":
            continue
        for retired_name in constraint["params"]:
            if retired_name in values:
                violations.append(f"{retired_name}={values[retired_name]!r}: {constraint['message']}")

    if violations:
        print(f"Rejected args for target '{target}':", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: run_profile_to_justfile.py {generate|validate|verify-source} ...",
              file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "validate":
        return _cli_validate(rest)
    if cmd == "verify-source":
        if len(rest) < 1:
            print("usage: verify-source <run_profile.json>", file=sys.stderr)
            return 2
        path = Path(rest[0])
        try:
            profile = load_run_profile(path)
            result = verify_source_authority(profile, path)
        except RunProfileValidationError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"{result['status']}: {result.get('source') or result.get('reason')}")
        return 0 if result["status"] == "VERIFIED" else 3
    if cmd == "generate":
        if len(rest) < 2:
            print("usage: generate <run_profile.json> <out justfile path>", file=sys.stderr)
            return 2
        generate_and_write(Path(rest[0]), Path(rest[1]))
        return 0
    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
