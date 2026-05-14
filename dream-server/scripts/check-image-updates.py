#!/usr/bin/env python3
"""
check-image-updates.py — compare every image pin in the repo against the
current upstream Docker Hub / GHCR tag list and suggest bumps.

Reads pins from:
  * extensions/services/*/compose*.yaml      (line 'image: <ref>')
  * installers/phases/08-images.sh           (PULL_LIST+=("<ref>|..."))

Resolves env-var defaults like ${WHISPER_IMAGE:-ghcr.io/...:0.9.0-rc.3-cpu}
to the default value so we still see the canonical pin.

Tag classification (per family of pins):
  semver    vX.Y.Z              (qdrant, kokoro)
  semver    X.Y.Z               (n8n)
  prefixed  cpu-X.Y.Z, cuda-X.Y.Z, cpu-X.Y.Z-grpc        (TEI)
  release   MAJOR.MINOR.PATCH-rcN-cpu/-cuda[-X.Y.Z]      (speaches)
  calver    YYYY.M.D[-hash]                              (searxng)
  digest    name@sha256:...                              (skipped — see ADR)

Mutable / pre-release tags (latest, *-master*, *-rc*, *nightly*, *-dev*,
sha-*) are never suggested.

Output modes:
  default   colored text table
  --json    JSON to stdout (for CI / dashboards)
  --strict  exit 1 if any service has an available bump (for CI gating)

Free-tier friendly: anonymous tokens, paginates GHCR via Link headers,
caps Docker Hub at 5 pages by default.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────
USER_AGENT = "dream-server-check-image-updates/1.0"
HTTP_TIMEOUT = 20
# Docker Hub returns 100 tags/page, ordered by last_updated (newest first).
# Five pages = 500 most-recently-pushed tags — plenty for any sane release
# cadence.
DEFAULT_DOCKERHUB_PAGES = 5
# GHCR returns up to 1000 tags/page in *alphabetical* order, not by date.
# So coverage scales linearly with pages.  Some repos (TEI) ship every
# commit as a SHA-pinned tag and have >5k tags total.  Fetch up to 10
# pages = 10k tags, enough to include every released semver tag.
DEFAULT_GHCR_PAGES = 10

# Tag fragments that indicate a non-stable/mutable tag we should never propose.
SKIP_FRAGMENTS = (
    "latest",
    "nightly",
    "-master",
    "-dev",
    "-pre",
    "-canary",
    "-edge",
    "-snapshot",
)
# Pre-release suffixes per semver: -alpha, -beta, -rc, -pre.NN, etc.
PRERELEASE_RE = re.compile(r"-(?:alpha|beta|rc|pre)(?:\.|\d|$)", re.IGNORECASE)

# ──────────────────────────────────────────────────────────────────────
# ANSI helpers
# ──────────────────────────────────────────────────────────────────────
def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


_COLOR = _supports_color()


def _c(code: str, txt: str) -> str:
    return f"\033[{code}m{txt}\033[0m" if _COLOR else txt


def red(s: str) -> str:
    return _c("31", s)


def green(s: str) -> str:
    return _c("32", s)


def yellow(s: str) -> str:
    return _c("33", s)


def cyan(s: str) -> str:
    return _c("36", s)


def gray(s: str) -> str:
    return _c("90", s)


def bold(s: str) -> str:
    return _c("1", s)


# ──────────────────────────────────────────────────────────────────────
# Image ref parsing
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ImageRef:
    raw: str
    registry: str  # docker.io, ghcr.io, …
    namespace: str  # qdrant, huggingface, n8nio, …
    name: str  # qdrant, text-embeddings-inference, n8n, …
    tag: str  # v1.16.3, cpu-1.9.1, 2.20.7, …
    digest: Optional[str] = None  # set if pinned by @sha256:…

    @property
    def repo(self) -> str:
        if self.registry == "docker.io":
            return f"{self.namespace}/{self.name}"
        return f"{self.namespace}/{self.name}"  # ghcr path uses same shape

    @property
    def display(self) -> str:
        host = "" if self.registry == "docker.io" else f"{self.registry}/"
        return f"{host}{self.repo}:{self.tag}"


_ENV_DEFAULT_RE = re.compile(r"\$\{[A-Z0-9_]+:-([^}]+)\}")


def _resolve_env_defaults(s: str) -> str:
    """Replace ${VAR:-default} with default so env-var pins are still parsed."""
    while True:
        m = _ENV_DEFAULT_RE.search(s)
        if not m:
            return s
        s = s[: m.start()] + m.group(1) + s[m.end() :]


def parse_image_ref(raw: str) -> ImageRef | None:
    raw = _resolve_env_defaults(raw.strip())
    if "@sha256:" in raw:
        # Digest pin — track but skip checking (intentional ADR-IMAGE-TAG-PINNING).
        body, digest = raw.split("@", 1)
        ref = parse_image_ref(body + ":pinned-by-digest")
        if ref:
            ref.digest = digest
            ref.raw = raw
        return ref
    if ":" not in raw:
        return None
    body, tag = raw.rsplit(":", 1)
    if "/" in body:
        first, rest = body.split("/", 1)
        if "." in first or ":" in first or first == "localhost":
            registry = first
            path = rest
        else:
            registry = "docker.io"
            path = body
    else:
        registry = "docker.io"
        path = f"library/{body}"
    if "/" in path:
        namespace, name = path.split("/", 1)
    else:
        namespace, name = "library", path
    return ImageRef(
        raw=raw, registry=registry, namespace=namespace, name=name, tag=tag
    )


# ──────────────────────────────────────────────────────────────────────
# Pin discovery
# ──────────────────────────────────────────────────────────────────────
@dataclass
class Pin:
    service: str  # qdrant, n8n, finance-vector, …
    file: Path
    line: int
    image: ImageRef
    source: str  # "compose" or "installer"


_IMAGE_LINE_RE = re.compile(r"^\s*image:\s*(\S+)")
_INSTALLER_LINE_RE = re.compile(r'PULL_LIST\+=\("([^"|]+)\|')


def discover_pins(repo_root: Path) -> list[Pin]:
    pins: list[Pin] = []

    # 1) extensions/services/*/compose*.yaml*
    services_root = repo_root / "extensions" / "services"
    if services_root.is_dir():
        for svc_dir in sorted(services_root.iterdir()):
            if not svc_dir.is_dir():
                continue
            sid = svc_dir.name
            for compose in sorted(svc_dir.glob("compose*.yaml*")):
                # Skip *.disabled in repo (those are the inactive defaults).
                if compose.name.endswith(".disabled"):
                    continue
                try:
                    text = compose.read_text(encoding="utf-8")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    m = _IMAGE_LINE_RE.match(line)
                    if not m:
                        continue
                    ref = parse_image_ref(m.group(1))
                    if ref is None:
                        continue
                    pins.append(
                        Pin(
                            service=sid,
                            file=compose,
                            line=lineno,
                            image=ref,
                            source="compose",
                        )
                    )

    # 2) installers/phases/08-images.sh
    installer = repo_root / "installers" / "phases" / "08-images.sh"
    if installer.is_file():
        try:
            text = installer.read_text(encoding="utf-8")
        except OSError:
            text = ""
        for lineno, line in enumerate(text.splitlines(), start=1):
            m = _INSTALLER_LINE_RE.search(line)
            if not m:
                continue
            ref = parse_image_ref(m.group(1))
            if ref is None:
                continue
            pins.append(
                Pin(
                    service=f"installer:{ref.name}",
                    file=installer,
                    line=lineno,
                    image=ref,
                    source="installer",
                )
            )
    return pins


# ──────────────────────────────────────────────────────────────────────
# Tag families
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TagFamily:
    """How a tag string is parsed into a sortable key."""

    name: str
    pattern: re.Pattern
    sort_key: Any  # callable(re.Match) -> tuple


def _semver_key(m: re.Match) -> tuple:
    return tuple(int(x) for x in m.groups())


def _calver_key(m: re.Match) -> tuple:
    # YYYY.M.D[-hash]; we ignore the hash for ordering.
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


# Order matters: more-specific first.  detect_family() picks the first match.
TAG_FAMILIES = [
    # cpu-1.9.3-grpc, cuda-12.4.1-1.9.3 etc. — keep simple "PREFIX-X.Y.Z"
    TagFamily(
        "prefixed-semver",
        re.compile(r"^([a-z]+(?:-[a-z]+)?)-(\d+)\.(\d+)\.(\d+)$"),
        lambda m: (m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))),
    ),
    # llama.cpp style monotonic build counter: server-bNNNN, server-cuda-bNNNN
    TagFamily(
        "prefixed-build",
        re.compile(r"^(server(?:-[a-z]+)*)-b(\d+)$"),
        lambda m: (m.group(1), int(m.group(2))),
    ),
    # vX.Y.Z (qdrant, kokoro, n8n-bare-v, open-webui, …)
    TagFamily(
        "v-semver",
        re.compile(r"^v(\d+)\.(\d+)\.(\d+)$"),
        _semver_key,
    ),
    # X.Y.Z (n8n)
    TagFamily(
        "semver",
        re.compile(r"^(\d+)\.(\d+)\.(\d+)$"),
        _semver_key,
    ),
    # X.Y.Z-suffix (postgres '17.9-alpine', caddy '2.8.4-alpine')
    # The suffix usually denotes a base-image variant; keep it constant.
    TagFamily(
        "semver-suffixed",
        re.compile(r"^(\d+)\.(\d+)\.(\d+)-([a-z][a-z0-9.-]*)$"),
        lambda m: (
            m.group(4),
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
        ),
    ),
    # vX.Y.Z-suffix  (litellm 'v1.81.3-stable')
    TagFamily(
        "v-semver-suffixed",
        re.compile(r"^v(\d+)\.(\d+)\.(\d+)-([a-z][a-z0-9.-]*)$"),
        lambda m: (
            m.group(4),
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
        ),
    ),
    # X.Y-suffix  (postgres '17.9-alpine')
    TagFamily(
        "semver-short-suffixed",
        re.compile(r"^(\d+)\.(\d+)-([a-z][a-z0-9.-]*)$"),
        lambda m: (m.group(3), int(m.group(1)), int(m.group(2))),
    ),
    # vX.Y  (comfyui v0.2 etc.)
    TagFamily(
        "v-semver-short",
        re.compile(r"^v(\d+)\.(\d+)$"),
        lambda m: (int(m.group(1)), int(m.group(2))),
    ),
    # CalVer YYYY.M.D[-hash]  (searxng)
    TagFamily(
        "calver",
        re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})(?:[-_].+)?$"),
        _calver_key,
    ),
]


def detect_family(tag: str):
    for fam in TAG_FAMILIES:
        if fam.pattern.match(tag):
            return fam
    return None


def is_skippable(tag: str) -> bool:
    low = tag.lower()
    if any(frag in low for frag in SKIP_FRAGMENTS):
        return True
    if PRERELEASE_RE.search(low):
        return True
    if low.startswith("sha-") or "-sha-" in low:
        return True
    return False


# ──────────────────────────────────────────────────────────────────────
# Registry clients
# ──────────────────────────────────────────────────────────────────────
def _http_get_json(url: str, headers: dict | None = None) -> tuple[Any, dict]:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.load(resp), dict(resp.headers)


def fetch_docker_hub_tags(repo: str, max_pages: int = DEFAULT_DOCKERHUB_PAGES) -> list:
    """repo = 'qdrant/qdrant' (Docker Hub)."""
    out: list[str] = []
    page = 1
    while page <= max_pages:
        url = (
            f"https://hub.docker.com/v2/repositories/{repo}/tags"
            f"?page_size=100&page={page}&ordering=last_updated"
        )
        try:
            body, _ = _http_get_json(url)
        except urllib.error.HTTPError as e:
            if e.code == 404 or page > 1:
                break
            raise
        results = body.get("results") or []
        if not results:
            break
        out.extend(t["name"] for t in results)
        if not body.get("next"):
            break
        page += 1
    return out


def fetch_ghcr_tags(repo: str, max_pages: int = DEFAULT_GHCR_PAGES) -> list:
    """repo = 'huggingface/text-embeddings-inference' (GHCR)."""
    token_url = f"https://ghcr.io/token?scope=repository:{repo}:pull"
    try:
        token_body, _ = _http_get_json(token_url)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GHCR token failed: {e}") from e
    token = token_body.get("token") or token_body.get("access_token")
    if not token:
        raise RuntimeError("GHCR token response missing 'token'")
    headers = {"Authorization": f"Bearer {token}"}

    out: list[str] = []
    url = f"https://ghcr.io/v2/{repo}/tags/list?n=1000"
    page = 0
    while url and page < max_pages:
        body, hdrs = _http_get_json(url, headers=headers)
        out.extend(body.get("tags") or [])
        link = hdrs.get("Link", "")
        m = re.search(r"<([^>]+)>;\s*rel=\"?next\"?", link)
        url = ("https://ghcr.io" + m.group(1)) if m else None
        page += 1
    return out


def fetch_tags(image: ImageRef, max_pages_dockerhub: int, max_pages_ghcr: int) -> list:
    if image.registry == "docker.io":
        return fetch_docker_hub_tags(image.repo, max_pages=max_pages_dockerhub)
    if image.registry == "ghcr.io":
        return fetch_ghcr_tags(image.repo, max_pages=max_pages_ghcr)
    raise RuntimeError(f"Unsupported registry: {image.registry}")


# ──────────────────────────────────────────────────────────────────────
# Best-tag selection
# ──────────────────────────────────────────────────────────────────────
@dataclass
class CheckResult:
    pin: Pin
    family: Optional[str]
    current: str
    latest: Optional[str]
    available_bump: bool
    incomplete: bool = False  # registry pagination missed newer tags
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "service": self.pin.service,
            "file": str(self.pin.file),
            "line": self.pin.line,
            "image": self.pin.image.display,
            "registry": self.pin.image.registry,
            "repo": self.pin.image.repo,
            "current": self.current,
            "latest": self.latest,
            "family": self.family,
            "available_bump": self.available_bump,
            "incomplete": self.incomplete,
            "note": self.note,
        }


def pick_latest(current_tag: str, all_tags: list) -> tuple:
    """Return (latest_tag_in_same_family, family_name) or (None, None).

    For ``prefixed-semver`` we additionally require the textual prefix to
    match the current pin's prefix exactly — otherwise we'd happily
    'upgrade' ``cpu-1.9.3`` to ``xpu-ipex-1.9.1`` because alphabetically
    ``xpu-ipex`` > ``cpu``.  The prefix encodes a hardware variant and is
    not interchangeable.
    """
    fam = detect_family(current_tag)
    if not fam:
        return None, None
    cur_match = fam.pattern.match(current_tag)
    cur_key = fam.sort_key(cur_match)
    # Lock variant if the family encodes one as a leading string component.
    cur_variant = cur_key[0] if isinstance(cur_key[0], str) else None

    candidates: list[tuple[Any, str]] = []
    for t in all_tags:
        if is_skippable(t):
            continue
        m = fam.pattern.match(t)
        if not m:
            continue
        cand_key = fam.sort_key(m)
        if cur_variant is not None and cand_key[0] != cur_variant:
            continue
        candidates.append((cand_key, t))
    if not candidates:
        return None, fam.name
    # For deterministic ordering on equal sort keys (e.g. two CalVer builds
    # on the same day), append the tag string itself as final tiebreaker.
    candidates.sort(key=lambda kv: (kv[0], kv[1]))
    return candidates[-1][1], fam.name


def check_pin(pin: Pin, max_pages_dockerhub: int, max_pages_ghcr: int) -> CheckResult:
    img = pin.image
    if img.digest:
        return CheckResult(
            pin=pin,
            family="digest",
            current=img.digest,
            latest=None,
            available_bump=False,
            note="pinned by digest (see ADR-IMAGE-TAG-PINNING)",
        )
    fam = detect_family(img.tag)
    if not fam:
        return CheckResult(
            pin=pin,
            family=None,
            current=img.tag,
            latest=None,
            available_bump=False,
            note="tag does not match a known family — manual review",
        )
    try:
        tags = fetch_tags(
            img,
            max_pages_dockerhub=max_pages_dockerhub,
            max_pages_ghcr=max_pages_ghcr,
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            pin=pin,
            family=fam.name,
            current=img.tag,
            latest=None,
            available_bump=False,
            note=f"registry query failed: {e}",
        )
    latest, _ = pick_latest(img.tag, tags)
    if not latest:
        return CheckResult(
            pin=pin,
            family=fam.name,
            current=img.tag,
            latest=None,
            available_bump=False,
            note="no comparable tag found in registry",
        )
    # Compare current vs latest using the family's sort key, not string compare.
    cur_key = fam.sort_key(fam.pattern.match(img.tag))
    new_key = fam.sort_key(fam.pattern.match(latest))
    if new_key < cur_key:
        # Highest tag we found ranks BELOW the current pin — almost
        # certainly a registry-pagination miss for repos with tens of
        # thousands of CI build tags (open-webui, llama.cpp, …).  Don't
        # propose a downgrade; flag for manual review instead.
        return CheckResult(
            pin=pin,
            family=fam.name,
            current=img.tag,
            latest=latest,
            available_bump=False,
            incomplete=True,
            note=(
                "current pin is newer than the highest tag we observed — "
                "registry has more tags than --max-pages-ghcr; check upstream manually"
            ),
        )
    same = new_key == cur_key
    return CheckResult(
        pin=pin,
        family=fam.name,
        current=img.tag,
        latest=latest,
        available_bump=not same,
        note="up to date" if same else "bump available",
    )


# ──────────────────────────────────────────────────────────────────────
# Dedup: same image referenced from compose + installer is one logical pin.
# ──────────────────────────────────────────────────────────────────────
def merge_duplicates(pins: list[Pin]) -> list[Pin]:
    """Keep the compose pin as canonical; treat installer pin as alias.

    The output preserves both for the report so users see drift between
    compose.yaml and installers/phases/08-images.sh."""
    seen: dict[tuple[str, str, str], Pin] = {}
    out: list[Pin] = []
    for p in pins:
        key = (p.image.registry, p.image.repo, p.image.tag)
        if key in seen and p.source == "installer":
            # Skip — already represented by compose pin with same tag.
            continue
        seen[key] = p
        out.append(p)
    return out


# ──────────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────────
def print_text_report(results: list[CheckResult]) -> None:
    if not results:
        print("No image pins discovered.")
        return

    bumps = [r for r in results if r.available_bump]
    locked = [
        r for r in results
        if not r.available_bump and r.latest and not r.incomplete
    ]
    other = [
        r for r in results
        if not r.available_bump and (r.latest is None or r.incomplete)
    ]

    width_svc = max(len(r.pin.service) for r in results) + 2
    width_repo = max(len(r.pin.image.display.split(":")[0]) for r in results) + 2

    def row(r: CheckResult) -> str:
        repo = r.pin.image.display.split(":")[0]
        cur = r.current
        new = r.latest or "—"
        if r.available_bump:
            arrow = green("→")
            new_c = green(new)
            tag_label = yellow(f"BUMP")
        elif r.latest and r.latest == r.current:
            arrow = gray("=")
            new_c = gray(new)
            tag_label = green("ok  ")
        else:
            arrow = gray("·")
            new_c = gray(new)
            tag_label = gray("?   ")
        return (
            f"  {tag_label} "
            f"{r.pin.service:<{width_svc}} "
            f"{repo:<{width_repo}} "
            f"{cur:>20} {arrow} {new_c}"
        )

    if bumps:
        print(bold(yellow(f"\nAvailable bumps ({len(bumps)}):")))
        for r in bumps:
            print(row(r))
            if r.note and r.note != "bump available":
                print(gray(f"      note: {r.note}"))

    if locked:
        print(bold(green(f"\nUp to date ({len(locked)}):")))
        for r in locked:
            print(row(r))

    if other:
        print(bold(gray(f"\nUnchecked ({len(other)}):")))
        for r in other:
            print(row(r))
            if r.note:
                print(gray(f"      {r.note}"))

    print()
    if bumps:
        print(
            cyan(
                f"To bump a pin, edit BOTH the compose.yaml AND "
                f"installers/phases/08-images.sh, then:"
            )
        )
        print(cyan("  git commit && git push && dream sync --pull --auto-restart"))
        print()


def print_json_report(results: list[CheckResult]) -> None:
    json.dump(
        {
            "tool": "check-image-updates",
            "version": 1,
            "results": [r.to_dict() for r in results],
            "summary": {
                "total": len(results),
                "bumps_available": sum(1 for r in results if r.available_bump),
                "up_to_date": sum(
                    1 for r in results if r.latest and not r.available_bump
                ),
                "unchecked": sum(1 for r in results if not r.latest),
            },
        },
        sys.stdout,
        indent=2,
    )
    print()


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="check-image-updates",
        description=(
            "Compare every image pin in the DreamServer repo against upstream "
            "Docker Hub / GHCR registries and suggest bumps."
        ),
    )
    p.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Repo root containing extensions/services/ and installers/ "
        "(default: cwd)",
    )
    p.add_argument(
        "--service",
        action="append",
        default=[],
        help="Limit to one or more service names (may be repeated). "
        "Matches Pin.service (e.g. 'qdrant', 'n8n', 'installer:n8n').",
    )
    p.add_argument(
        "--max-pages-dockerhub",
        type=int,
        default=DEFAULT_DOCKERHUB_PAGES,
        help=f"Docker Hub pagination cap, 100 tags/page "
        f"(default: {DEFAULT_DOCKERHUB_PAGES})",
    )
    p.add_argument(
        "--max-pages-ghcr",
        type=int,
        default=DEFAULT_GHCR_PAGES,
        help=f"GHCR pagination cap, 1000 tags/page "
        f"(default: {DEFAULT_GHCR_PAGES})",
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if at least one bump is available (CI gate)",
    )
    args = p.parse_args(argv)

    pins = discover_pins(args.project_dir)
    pins = merge_duplicates(pins)
    if args.service:
        wanted = set(args.service)
        pins = [p for p in pins if p.service in wanted]
    if not pins:
        print("No matching pins found.", file=sys.stderr)
        return 0

    if not args.json:
        print(
            cyan(
                f"→ Checking {len(pins)} pin(s) against upstream registries "
                f"(this may take a few seconds)…"
            )
        )

    results = [
        check_pin(
            p,
            max_pages_dockerhub=args.max_pages_dockerhub,
            max_pages_ghcr=args.max_pages_ghcr,
        )
        for p in pins
    ]

    if args.json:
        print_json_report(results)
    else:
        print_text_report(results)

    if args.strict and any(r.available_bump for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

