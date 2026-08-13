"""Skills loader for agent capabilities."""

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence, cast

import yaml

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# Opening ---, YAML body (group 1), closing --- on its own line; supports CRLF.
_STRIP_SKILL_FRONTMATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)
_SKILL_REFERENCE = re.compile(r"(?<![\w$])\$([A-Za-z0-9_-]+)")

# Activation values understood by SkillDescriptor.
_SKILL_ACTIVATIONS = ("auto", "manual", "always", "disabled")

# Deterministic term matching for local skill recall (FR-3).
_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+")
_SKILL_PHRASE_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")


def _normalize_str_list(value: object) -> tuple[str, ...]:
    """Coerce frontmatter tags/triggers (str, list, JSON str) to a tuple of strings."""
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ()
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return (raw,)
            return tuple(str(item).strip() for item in parsed if str(item).strip())
        return (raw,)
    if isinstance(value, list):
        items = cast(list[object], value)
        return tuple(str(item).strip() for item in items if str(item).strip())
    return ()


def _tokenize(text: str) -> set[str]:
    """Split text into deterministic match terms (latin words + CJK bigrams)."""
    if not text:
        return set()
    lowered = text.lower()
    tokens = _WORD_TOKEN_RE.findall(lowered)
    for chunk in _CJK_TOKEN_RE.findall(lowered):
        if len(chunk) >= 2:
            tokens.append(chunk)
            tokens.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
    return {token for token in tokens if token}


def _estimate_tokens(text: str) -> int:
    """Rough token count: tiktoken when available, else a UTF-8 byte budget."""
    if not text:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, len(text.encode("utf-8")) // 4)


@dataclass(frozen=True)
class SkillDescriptor:
    """Read-only matching metadata for one skill (FR-2).

    Attributes:
        name: Skill directory name.
        source: "workspace" or "builtin".
        description: One-line description (falls back to the skill name).
        availability: Whether requirements (bins/env) are met.
        activation: "auto" | "manual" | "always" | "disabled".
        tags: Optional frontmatter tags that improve recall.
        triggers: Optional frontmatter triggers that improve recall.
        auto_bind_triggers: Optional action phrases eligible for auto-binding.
        auto_bind_requires: Objective facts required before auto-binding.
        content_fingerprint: Short hash of the SKILL.md body.
        missing_requirements: Human-readable unmet requirements, when any.
    """

    name: str
    source: str
    description: str
    availability: bool
    activation: str = "auto"
    missing_requirements: str = ""
    tags: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    auto_bind_triggers: tuple[str, ...] = ()
    auto_bind_requires: tuple[str, ...] = ()
    content_fingerprint: str = ""


@dataclass(frozen=True)
class SkillRecallResult:
    """Outcome of deterministic local skill recall (FR-3).

    Attributes:
        candidates: Matching candidate names, best score first.
        bound: Names actually bound (subject to budget); subset of candidates.
        reason: "none" | "weak_match" | "high_confidence" |
            "ambiguous_multi_candidate" | "budget_limited" |
            "missing_required_fact".
    """

    candidates: tuple[str, ...] = ()
    bound: tuple[str, ...] = ()
    reason: str = "none"
    bound_token_estimate: int = 0


@dataclass(frozen=True)
class _SkillFileCacheEntry:
    """Parsed in-process representation of one unchanged ``SKILL.md`` file."""

    signature: tuple[int, int]
    content: str
    frontmatter: dict[str, object] | None
    fingerprint: str


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None, disabled_skills: set[str] | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.disabled_skills = disabled_skills or set()
        self._skill_file_cache: dict[Path, _SkillFileCacheEntry] = {}

    def _find_skill_path(self, name: str) -> Path | None:
        """Resolve *name* with the same workspace-over-builtin precedence as loading."""
        roots = [self.workspace_skills]
        if self.builtin_skills:
            roots.append(self.builtin_skills)
        for root in roots:
            path = root / name / "SKILL.md"
            if path.exists():
                return path
        return None

    def _read_skill_entry(self, path: Path) -> _SkillFileCacheEntry | None:
        """Read and parse a Skill file once, invalidating on mtime or size changes."""
        try:
            stat = path.stat()
        except OSError:
            self._skill_file_cache.pop(path, None)
            return None
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = self._skill_file_cache.get(path)
        if cached is not None and cached.signature == signature:
            return cached
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            self._skill_file_cache.pop(path, None)
            return None
        entry = _SkillFileCacheEntry(
            signature=signature,
            content=content,
            frontmatter=self._frontmatter_from_content(content),
            fingerprint=hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
        )
        self._skill_file_cache[path] = entry
        return entry

    @staticmethod
    def _frontmatter_from_content(content: str) -> dict[str, object] | None:
        """Parse frontmatter while keeping YAML-native value types intact."""
        if not content.startswith("---"):
            return None
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if not match:
            return None
        try:
            parsed = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return None
        if not isinstance(parsed, dict):
            return None
        return {str(key): value for key, value in cast(dict[object, object], parsed).items()}

    def _skill_entries_from_dir(self, base: Path, source: str, *, skip_names: set[str] | None = None) -> list[dict[str, str]]:
        if not base.exists():
            return []
        entries: list[dict[str, str]] = []
        for skill_dir in base.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            name = skill_dir.name
            if skip_names is not None and name in skip_names:
                continue
            entries.append({"name": name, "path": str(skill_file), "source": source})
        return entries

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills = self._skill_entries_from_dir(self.workspace_skills, "workspace")
        workspace_names = {entry["name"] for entry in skills}
        if self.builtin_skills and self.builtin_skills.exists():
            skills.extend(
                self._skill_entries_from_dir(self.builtin_skills, "builtin", skip_names=workspace_names)
            )

        if self.disabled_skills:
            skills = [s for s in skills if s["name"] not in self.disabled_skills]

        if filter_unavailable:
            return [skill for skill in skills if self._check_requirements(self._get_skill_meta(skill["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        path = self._find_skill_path(name)
        entry = self._read_skill_entry(path) if path is not None else None
        return entry.content if entry is not None else None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_names: List of skill names to load.

        Returns:
            Formatted skills content.
        """
        parts = [
            f"### Skill: {name}\n\n{self._strip_frontmatter(markdown)}"
            for name in skill_names
            if (markdown := self.load_skill(name))
        ]
        return "\n\n---\n\n".join(parts)

    def get_explicitly_invoked_skills(self, text: str) -> list[str]:
        """Resolve ``$skill-name`` references to enabled, available skills."""
        if not text:
            return []
        available = {
            entry["name"]
            for entry in self.list_skills(filter_unavailable=True)
        }
        invoked: list[str] = []
        for match in _SKILL_REFERENCE.finditer(text):
            name = match.group(1)
            if name in available and name not in invoked:
                invoked.append(name)
        return invoked

    def build_skills_summary(self, exclude: set[str] | None = None) -> str:
        """
        Build a summary of all skills (name, description, path, availability).

        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.

        Args:
            exclude: Set of skill names to omit from the summary.

        Returns:
            Markdown-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        sections: list[str] = []
        groups = (
            ("Workspace skills", "workspace", self.workspace_skills),
            ("Built-in skills", "builtin", self.builtin_skills),
        )
        for label, source, root in groups:
            entries = [
                entry
                for entry in all_skills
                if entry["source"] == source and (not exclude or entry["name"] not in exclude)
            ]
            if not entries:
                continue

            lines = [f"### {label} (`{root.expanduser().resolve()}`)"]
            for entry in entries:
                skill_name = entry["name"]
                meta = self._get_skill_meta(skill_name)
                available = self._check_requirements(meta)
                desc = self.get_skill_description(skill_name)
                suffix = ""
                if not available:
                    missing = self._get_missing_requirements(meta)
                    suffix = f" (unavailable: {missing})" if missing else " (unavailable)"
                relative_path = Path(entry["path"]).relative_to(root).as_posix()
                lines.append(f"- **{skill_name}** — {desc}{suffix}  `{relative_path}`")
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    @staticmethod
    def _requirement_lists(skill_meta: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Return (bins, env) lists from skill metadata, tolerating null/wrong shapes."""
        requires = cast(dict[str, Any], skill_meta.get("requires") or {})
        if not isinstance(skill_meta.get("requires") or {}, dict):
            return [], []
        bins_raw: object = requires.get("bins") or []
        env_raw: object = requires.get("env") or []
        bins = [value for value in cast(list[object], bins_raw) if isinstance(value, str) and value.strip()] if isinstance(bins_raw, list) else []
        env = [value for value in cast(list[object], env_raw) if isinstance(value, str) and value.strip()] if isinstance(env_raw, list) else []
        return bins, env

    def _get_missing_requirements(self, skill_meta: dict[str, Any]) -> str:
        """Get a description of missing requirements."""
        required_bins, required_env_vars = self._requirement_lists(skill_meta)
        return ", ".join(
            [f"CLI: {command_name}" for command_name in required_bins if not shutil.which(command_name)]
            + [f"ENV: {env_name}" for env_name in required_env_vars if not os.environ.get(env_name)]
        )

    def get_skill_availability(self, name: str) -> tuple[bool, str]:
        """Return whether a skill can run and why not when it cannot."""
        meta = self._get_skill_meta(name)
        available = self._check_requirements(meta)
        return available, "" if available else self._get_missing_requirements(meta)

    def get_skill_requirements(self, name: str) -> dict[str, list[str]]:
        """Return explicit command/env requirements and currently missing entries."""
        bins, env = self._requirement_lists(self._get_skill_meta(name))
        return {
            "bins": bins,
            "env": env,
            "missing_bins": [value for value in bins if not shutil.which(value)],
            "missing_env": [value for value in env if not os.environ.get(value)],
        }

    def get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        description = meta.get("description") if meta else None
        if isinstance(description, str) and description:
            return description
        return name  # Fallback to skill name

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return content
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if match:
            return content[match.end():].strip()
        return content

    def _parse_nanobot_metadata(self, raw: object) -> dict[str, Any]:
        """Extract nanobot/openclaw metadata from a frontmatter field.

        ``raw`` may be a dict (already parsed by yaml.safe_load) or a JSON str.
        """
        if isinstance(raw, dict):
            data = cast(dict[str, Any], raw)
        elif isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        else:
            return {}
        if not isinstance(data, dict):
            return {}
        data_object = cast(dict[str, Any], data)
        payload = data_object.get("nanobot", data_object.get("openclaw", {}))
        return cast(dict[str, Any], payload) if isinstance(payload, dict) else {}

    def _check_requirements(self, skill_meta: dict[str, Any]) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        required_bins, required_env_vars = self._requirement_lists(skill_meta)
        return all(shutil.which(cmd) for cmd in required_bins) and all(
            os.environ.get(var) for var in required_env_vars
        )

    def _get_skill_meta(self, name: str) -> dict[str, Any]:
        """Get nanobot metadata for a skill (cached in frontmatter)."""
        raw_meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(raw_meta.get("metadata"))

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        return [
            entry["name"]
            for entry in self.list_skills(filter_unavailable=True)
            if (meta := self.get_skill_metadata(entry["name"]) or {})
            and (
                self._parse_nanobot_metadata(meta.get("metadata")).get("always")
                or meta.get("always")
            )
        ]

    def get_skill_metadata(self, name: str) -> dict[str, object] | None:
        """
        Get metadata from a skill's frontmatter.

        Args:
            name: Skill name.

        Returns:
            Metadata dict or None.
        """
        path = self._find_skill_path(name)
        entry = self._read_skill_entry(path) if path is not None else None
        # Return a copy so callers retain the old fresh-dict contract.
        return dict(entry.frontmatter) if entry is not None and entry.frontmatter is not None else None

    # ------------------------------------------------------------------
    # SkillDescriptor + deterministic local recall (FR-2 / FR-3)
    # ------------------------------------------------------------------

    def list_skill_descriptors(self) -> list[SkillDescriptor]:
        """Build read-only :class:`SkillDescriptor` views for all skills.

        Legacy skills without the new frontmatter fields default to
        ``activation=auto``; ``disabled``/``manual``/``always`` semantics are
        preserved. Skills listed in ``disabled_skills`` are not included.
        """
        descriptors: list[SkillDescriptor] = []
        for entry in self.list_skills(filter_unavailable=False):
            name = entry["name"]
            meta = self.get_skill_metadata(name) or {}
            nanobot_meta = self._parse_nanobot_metadata(meta.get("metadata"))
            description = self.get_skill_description(name)
            # get_skill_description reads the top-level frontmatter; fall back
            # to the nanobot metadata description when the top level lacks one.
            if description == name:
                meta_desc = nanobot_meta.get("description")
                if isinstance(meta_desc, str) and meta_desc:
                    description = meta_desc
            available = self._check_requirements(nanobot_meta)
            missing = "" if available else self._get_missing_requirements(nanobot_meta)
            tags = _normalize_str_list(
                nanobot_meta.get("tags", meta.get("tags"))
            )
            triggers = _normalize_str_list(
                nanobot_meta.get("triggers", meta.get("triggers"))
            )
            auto_bind = nanobot_meta.get("autoBind")
            auto_bind_meta = cast(dict[str, object], auto_bind) if isinstance(auto_bind, dict) else {}
            descriptors.append(
                SkillDescriptor(
                    name=name,
                    source=entry["source"],
                    description=description,
                    availability=available,
                    activation=self._resolve_activation(nanobot_meta, meta),
                    missing_requirements=missing,
                    tags=tags,
                    triggers=triggers,
                    auto_bind_triggers=_normalize_str_list(auto_bind_meta.get("triggers")),
                    auto_bind_requires=_normalize_str_list(auto_bind_meta.get("requires")),
                    content_fingerprint=self._content_fingerprint(name),
                )
            )
        return descriptors

    @staticmethod
    def _resolve_activation(nanobot_meta: dict[str, Any], front_meta: dict[str, Any]) -> str:
        """Resolve activation from frontmatter, falling back to legacy booleans.

        Priority: explicit ``activation`` string (nanobot metadata, then
        top-level) -> ``always``/``manual``/``disabled`` booleans -> ``auto``.
        """
        for source in (nanobot_meta, front_meta):
            value = source.get("activation")
            if isinstance(value, str) and value.strip().lower() in _SKILL_ACTIVATIONS:
                return value.strip().lower()
        for source in (nanobot_meta, front_meta):
            if source.get("always") is True:
                return "always"
            if source.get("manual") is True:
                return "manual"
            if source.get("disabled") is True:
                return "disabled"
        return "auto"

    def _content_fingerprint(self, name: str) -> str:
        """Short stable hash of the SKILL.md body for change detection."""
        path = self._find_skill_path(name)
        entry = self._read_skill_entry(path) if path is not None else None
        return entry.fingerprint if entry is not None else ""

    def recall_skill_candidates(
        self,
        text: str,
        *,
        exclude: Sequence[str] = (),
        max_count: int = 2,
        token_budget: int = 2000,
        has_current_media: bool = False,
    ) -> SkillRecallResult:
        """Deterministic local skill recall for the skill-guidance lane (FR-3).

        Term-overlap matching against each candidate skill's name, description,
        tags and triggers. Description-only matches remain observable candidates,
        but automatic binding requires one unique strong phrase hit and any
        declared objective facts. A skill can provide ``autoBind.triggers`` to
        use action phrases instead of its name/tags/triggers as strong signals,
        and ``autoBind.requires: [current_media]`` to require an attachment.
        Skills that are unavailable, ``disabled``, ``manual`` or ``always`` are
        excluded, as are names in *exclude* (explicit ``$skill`` references).
        """
        if not text:
            return SkillRecallResult()
        query_tokens = _tokenize(text)
        if not query_tokens:
            return SkillRecallResult()
        excluded = set(exclude or ())
        normalized_text = _SKILL_PHRASE_RE.sub("", text.lower())
        scored: list[tuple[int, int, bool, str]] = []
        for descriptor in self.list_skill_descriptors():
            if descriptor.activation != "auto" or not descriptor.availability:
                continue
            if descriptor.name in excluded:
                continue
            score = self._match_score(query_tokens, descriptor)
            if score > 0:
                strong_score = self._strong_match_score(normalized_text, query_tokens, descriptor)
                requirements_met = self._auto_bind_requirements_met(
                    descriptor,
                    has_current_media=has_current_media,
                )
                scored.append((score, strong_score, requirements_met, descriptor.name))
        if not scored:
            return SkillRecallResult()
        scored.sort(key=lambda item: (-item[0], item[3]))
        candidates = tuple(name for _, _, _, name in scored)
        strong_candidates = [candidate for candidate in scored if candidate[1] > 0]
        if not strong_candidates:
            return SkillRecallResult(candidates=candidates, reason="weak_match")
        eligible_strong_candidates = [candidate for candidate in strong_candidates if candidate[2]]
        if not eligible_strong_candidates:
            return SkillRecallResult(candidates=candidates, reason="missing_required_fact")
        # Different explicit activation phrases are an ambiguity, regardless
        # of their spelling length. Choosing ``github`` over ``git`` merely
        # because one name has more characters would be false confidence.
        if len(eligible_strong_candidates) > 1:
            return SkillRecallResult(candidates=candidates, reason="ambiguous_multi_candidate")
        top = eligible_strong_candidates[0]
        # Automatic loading is deliberately a single-workflow action. The
        # existing max_count setting remains a compatible ceiling, while a
        # low-ranked candidate can never be added merely to fill that budget.
        bound, bound_token_estimate = self._bind_with_budget(
            [(top[0], top[1], top[3])], max_count=max_count, token_budget=token_budget
        )
        if not bound:
            return SkillRecallResult(candidates=candidates, reason="budget_limited")
        return SkillRecallResult(
            candidates=candidates,
            bound=bound,
            reason="high_confidence",
            bound_token_estimate=bound_token_estimate,
        )

    @staticmethod
    def _match_score(query_tokens: set[str], descriptor: SkillDescriptor) -> int:
        """Heuristic term-overlap score: name > tags/triggers > description."""
        score = 0
        name_tokens = _tokenize(descriptor.name)
        if name_tokens & query_tokens:
            score += 5
        tag_tokens = _tokenize(" ".join((*descriptor.tags, *descriptor.triggers)))
        score += 2 * len(tag_tokens & query_tokens)
        desc_tokens = _tokenize(descriptor.description)
        score += len(desc_tokens & query_tokens)
        return score

    @staticmethod
    def _strong_match_score(
        normalized_text: str, query_tokens: set[str], descriptor: SkillDescriptor
    ) -> int:
        """Score exact activation phrases; generic token overlap is not a bind signal."""
        phrases = descriptor.auto_bind_triggers or (
            descriptor.name,
            *descriptor.tags,
            *descriptor.triggers,
        )
        uses_declared_auto_bind_triggers = bool(descriptor.auto_bind_triggers)
        strongest = 0
        for phrase in phrases:
            normalized_phrase = _SKILL_PHRASE_RE.sub("", phrase.lower())
            if not normalized_phrase:
                continue
            # Two Latin characters (for example ``my``) are too generic to
            # activate a workflow. CJK bigrams remain useful, so accept them.
            latin_only = normalized_phrase.isascii()
            if (latin_only and len(normalized_phrase) < 3) or (
                not latin_only and len(normalized_phrase) < 2
            ):
                continue
            if normalized_phrase in normalized_text:
                strongest = max(strongest, 40 + len(normalized_phrase))
                continue
            if not latin_only:
                # Allow natural Chinese wording to insert modifiers into a
                # trigger ("提取这张图片里的文字") without allowing one
                # generic bigram such as "内容" to activate a workflow.
                phrase_bigrams = {
                    token
                    for token in _tokenize(normalized_phrase)
                    if len(token) == 2 and _CJK_TOKEN_RE.fullmatch(token)
                }
                shared_bigrams = phrase_bigrams & query_tokens
                first_bigram = normalized_phrase[:2]
                # A declared auto-binding phrase is an action contract. Its
                # action prefix must appear before accepting fuzzy CJK wording;
                # otherwise a passive topic such as "上下文窗口" would activate
                # the declared action "检查上下文窗口".
                has_action_prefix = first_bigram in query_tokens
                if len(shared_bigrams) >= 2 and (
                    not uses_declared_auto_bind_triggers or has_action_prefix
                ):
                    strongest = max(strongest, 20 + len(shared_bigrams))
        return strongest

    @staticmethod
    def _auto_bind_requirements_met(
        descriptor: SkillDescriptor,
        *,
        has_current_media: bool,
    ) -> bool:
        """Return whether declared auto-binding facts are true for this turn.

        Unknown requirements deliberately fail closed. They are user-authored
        safety constraints, so a typo may suppress auto-loading but must never
        make a workflow easier to inject.
        """
        for requirement in descriptor.auto_bind_requires:
            if requirement == "current_media" and has_current_media:
                continue
            return False
        return True

    def _bind_with_budget(
        self,
        scored: Sequence[tuple[int, int, str]],
        *,
        max_count: int,
        token_budget: int,
    ) -> tuple[tuple[str, ...], int]:
        """Greedily bind top candidates until count/token budgets are exhausted."""
        bound: list[str] = []
        total_tokens = 0
        for _, _, name in scored:
            if len(bound) >= max_count:
                break
            content = self.load_skill(name) or ""
            tokens = _estimate_tokens(content)
            if token_budget > 0 and total_tokens + tokens > token_budget:
                break
            bound.append(name)
            total_tokens += tokens
        return tuple(bound), total_tokens
