"""Rule-based activity classification with confidence, reason and source.

Principles:
- A program or site with several common uses (YouTube, search engines, video players) is
  ``UNKNOWN`` with a reason instead of being forced into a category.
- A browser without a reported site is ``UNKNOWN`` ("browser activity details unavailable").
- The user's rules (created from corrections) win over built-in rules; a per-span correction
  wins over both. Corrections are optional: everything is classified without user input.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from focuslab.browser import BROWSER_EXES
from focuslab.config import NEUTRAL_APPS
from focuslab.domain.activity import ActivitySpan, Category, ClassReason, ClassSource, SpanKind
from focuslab.i18n import LocalizedMapping

CLASS_REASON_TEXT = LocalizedMapping(
    {
        ClassReason.APP_RULE: "Built-in program rule",
        ClassReason.SITE_RULE: "Built-in site rule",
        ClassReason.GAME_LIBRARY: "Program in a game library folder",
        ClassReason.AMBIGUOUS_APP: "Multiple possible uses; classification deferred",
        ClassReason.AMBIGUOUS_SITE: (
            "Site may be used for study or entertainment; classification deferred"
        ),
        ClassReason.BROWSER_NO_SITE: "Browser activity details unavailable",
        ClassReason.NEUTRAL_SHELL: "Desktop, app switcher, or FocusLab",
        ClassReason.UNREADABLE_APP: "Cannot read the program name",
        ClassReason.NO_RULE: "No matching rule",
        ClassReason.IDLE: "No keyboard or mouse input",
        ClassReason.LOCKED: "Screen locked",
        ClassReason.USER_APP_RULE: "Your program classification rule",
        ClassReason.USER_SITE_RULE: "Your site classification rule",
        ClassReason.USER_CORRECTION: "You corrected this interval",
        ClassReason.EXCLUDED: "Excluded from recording by you",
    }
)

C = Category
# executable -> (category, confidence)
APP_RULES: dict[str, tuple[Category, float]] = {
    **dict.fromkeys(
        (
            "code.exe",
            "cursor.exe",
            "pycharm64.exe",
            "idea64.exe",
            "webstorm64.exe",
            "clion64.exe",
            "goland64.exe",
            "rider64.exe",
            "phpstorm64.exe",
            "studio64.exe",
            "devenv.exe",
            "sublime_text.exe",
            "notepad++.exe",
            "windowsterminal.exe",
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "mintty.exe",
            "git-bash.exe",
            "githubdesktop.exe",
            "postman.exe",
            "dbeaver.exe",
            "docker desktop.exe",
            "wsl.exe",
            "zed.exe",
            "vim.exe",
            "gvim.exe",
        ),
        (C.DEVELOPMENT, 0.9),
    ),
    **dict.fromkeys(
        (
            "winword.exe",
            "hwp.exe",
            "hword.exe",
            "powerpnt.exe",
            "swriter.exe",
            "typora.exe",
            "obsidian.exe",
            "wordpad.exe",
            "notepad.exe",
        ),
        (C.DOCUMENTATION, 0.8),
    ),
    **dict.fromkeys(
        (
            "excel.exe",
            "onenote.exe",
            "notion.exe",
            "figma.exe",
            "acrord32.exe",
            "calculator.exe",
            "todo.exe",
            "evernote.exe",
            "claude.exe",
            "chatgpt.exe",
        ),
        (C.PRODUCTIVITY, 0.7),
    ),
    **dict.fromkeys(("acrobat.exe", "sumatrapdf.exe", "anki.exe", "zotero.exe"), (C.STUDY, 0.6)),
    **dict.fromkeys(
        (
            "slack.exe",
            "ms-teams.exe",
            "teams.exe",
            "kakaotalk.exe",
            "zoom.exe",
            "outlook.exe",
            "olk.exe",
            "telegram.exe",
            "whatsapp.exe",
            "line.exe",
            "thunderbird.exe",
        ),
        (C.COMMUNICATION, 0.85),
    ),
    "discord.exe": (C.COMMUNICATION, 0.6),
    **dict.fromkeys(("spotify.exe", "netflix.exe", "melon.exe"), (C.ENTERTAINMENT, 0.8)),
    **dict.fromkeys(
        (
            "steam.exe",
            "epicgameslauncher.exe",
            "battle.net.exe",
            "riotclientservices.exe",
            "leagueclient.exe",
            "league of legends.exe",
            "valorant.exe",
            "minecraft.exe",
            "xboxapp.exe",
            "gamebar.exe",
        ),
        (C.GAMING, 0.8),
    ),
}
# Video players play lectures and films alike.
AMBIGUOUS_APPS = frozenset(
    {
        "vlc.exe",
        "potplayermini64.exe",
        "potplayer.exe",
        "mpc-hc64.exe",
        "wmplayer.exe",
        "video.ui.exe",
        "music.ui.exe",
    }
)

# hostname suffix -> (category, confidence)
SITE_RULES: dict[str, tuple[Category, float]] = {
    **dict.fromkeys(
        (
            "github.com",
            "gitlab.com",
            "bitbucket.org",
            "stackoverflow.com",
            "stackexchange.com",
            "npmjs.com",
            "pypi.org",
            "vercel.com",
            "codepen.io",
            "replit.com",
            "huggingface.co",
            "localhost",
            "leetcode.com",
            "programmers.co.kr",
            "acmicpc.net",
            "codeforces.com",
        ),
        (C.DEVELOPMENT, 0.85),
    ),
    "local-address": (C.DEVELOPMENT, 0.5),
    **dict.fromkeys(
        (
            "docs.python.org",
            "developer.mozilla.org",
            "learn.microsoft.com",
            "wikipedia.org",
            "arxiv.org",
            "scholar.google.com",
            "dbpia.co.kr",
            "riss.kr",
            "researchgate.net",
            "readthedocs.io",
            "chatgpt.com",
            "claude.ai",
            "perplexity.ai",
            "gemini.google.com",
        ),
        (C.RESEARCH, 0.75),
    ),
    **dict.fromkeys(
        (
            "coursera.org",
            "edx.org",
            "khanacademy.org",
            "inflearn.com",
            "udemy.com",
            "classroom.google.com",
            "duolingo.com",
            "boostcourse.org",
            "kocw.net",
            "kmooc.kr",
        ),
        (C.STUDY, 0.8),
    ),
    **dict.fromkeys(
        ("docs.google.com", "notion.so", "overleaf.com", "hackmd.io", "office.com"),
        (C.DOCUMENTATION, 0.7),
    ),
    **dict.fromkeys(
        (
            "drive.google.com",
            "calendar.google.com",
            "figma.com",
            "trello.com",
            "atlassian.net",
            "miro.com",
            "linear.app",
        ),
        (C.PRODUCTIVITY, 0.75),
    ),
    **dict.fromkeys(
        (
            "mail.google.com",
            "outlook.live.com",
            "outlook.office.com",
            "slack.com",
            "teams.microsoft.com",
            "web.whatsapp.com",
            "mail.naver.com",
            "discord.com",
        ),
        (C.COMMUNICATION, 0.8),
    ),
    **dict.fromkeys(
        (
            "netflix.com",
            "twitch.tv",
            "disneyplus.com",
            "tving.com",
            "wavve.com",
            "coupangplay.com",
            "instagram.com",
            "facebook.com",
            "x.com",
            "twitter.com",
            "tiktok.com",
            "webtoons.com",
            "comic.naver.com",
            "chzzk.naver.com",
            "afreecatv.com",
        ),
        (C.ENTERTAINMENT, 0.8),
    ),
    "reddit.com": (C.ENTERTAINMENT, 0.5),
    **dict.fromkeys(("store.steampowered.com", "op.gg", "epicgames.com"), (C.GAMING, 0.6)),
}
# Sites whose name says nothing about the purpose: lectures and entertainment, searches
# for anything. They stay UNKNOWN unless the user decides otherwise.
AMBIGUOUS_SITES = frozenset(
    {
        "youtube.com",
        "youtu.be",
        "google.com",
        "google.co.kr",
        "naver.com",
        "daum.net",
        "bing.com",
        "duckduckgo.com",
        "tistory.com",
        "blog.naver.com",
        "medium.com",
        "velog.io",
    }
)
_AMBIGUOUS = dict.fromkeys(AMBIGUOUS_SITES)

# AI assistants: asking about a concept can be study or anything else.
AI_APPS = frozenset({"claude.exe", "chatgpt.exe", "copilot.exe", "perplexity.exe"})
AI_SITES = dict.fromkeys(
    ("claude.ai", "chatgpt.com", "perplexity.ai", "gemini.google.com", "copilot.microsoft.com")
)


def suffix_match(domain: str, table: Mapping[str, object]) -> str | None:
    "Longest suffix of ``domain`` that is a key of ``table`` (``a.b.c`` -> ``b.c`` -> ``c``)."
    parts = domain.split(".")
    for i in range(len(parts)):
        candidate = ".".join(parts[i:])
        if candidate in table:
            return candidate
    return None


@dataclass(frozen=True)
class Classification:
    category: Category
    confidence: float
    reason: ClassReason
    source: ClassSource


@dataclass(frozen=True)
class UserRules:
    """Rules from corrections: executable or hostname suffix -> category."""

    apps: Mapping[str, Category]
    sites: Mapping[str, Category]

    @staticmethod
    def empty() -> "UserRules":
        return UserRules({}, {})


def classify(
    kind: SpanKind,
    exe_name: str | None,
    domain: str | None = None,
    *,
    game_library: bool = False,
    excluded: bool = False,
    user: UserRules | None = None,
) -> Classification:
    if kind is SpanKind.IDLE:
        return Classification(C.BREAK, 1.0, ClassReason.IDLE, ClassSource.SYSTEM)
    if kind is SpanKind.LOCKED:
        return Classification(C.BREAK, 1.0, ClassReason.LOCKED, ClassSource.SYSTEM)
    if excluded:
        return Classification(C.UNKNOWN, 0.0, ClassReason.EXCLUDED, ClassSource.SYSTEM)
    user = user or UserRules.empty()
    if domain:
        site = suffix_match(domain, user.sites)
        if site:
            return Classification(
                user.sites[site], 1.0, ClassReason.USER_SITE_RULE, ClassSource.USER_RULE
            )
    if exe_name and exe_name in user.apps:
        return Classification(
            user.apps[exe_name], 1.0, ClassReason.USER_APP_RULE, ClassSource.USER_RULE
        )
    if exe_name is None:
        return Classification(C.UNKNOWN, 0.0, ClassReason.UNREADABLE_APP, ClassSource.RULE)
    if exe_name in BROWSER_EXES or domain:
        return _classify_site(domain)
    if exe_name in NEUTRAL_APPS:
        return Classification(C.UNKNOWN, 0.0, ClassReason.NEUTRAL_SHELL, ClassSource.RULE)
    if game_library:
        return Classification(C.GAMING, 0.85, ClassReason.GAME_LIBRARY, ClassSource.RULE)
    if exe_name in APP_RULES:
        category, confidence = APP_RULES[exe_name]
        return Classification(category, confidence, ClassReason.APP_RULE, ClassSource.RULE)
    if exe_name in AMBIGUOUS_APPS:
        return Classification(C.UNKNOWN, 0.3, ClassReason.AMBIGUOUS_APP, ClassSource.RULE)
    return Classification(C.UNKNOWN, 0.0, ClassReason.NO_RULE, ClassSource.RULE)


def _classify_site(domain: str | None) -> Classification:
    if not domain:
        return Classification(C.UNKNOWN, 0.0, ClassReason.BROWSER_NO_SITE, ClassSource.RULE)
    site = suffix_match(domain, SITE_RULES)
    vague = suffix_match(domain, _AMBIGUOUS)
    if vague and (site is None or len(vague) > len(site)):  # the more specific match wins:
        return Classification(C.UNKNOWN, 0.3, ClassReason.AMBIGUOUS_SITE, ClassSource.RULE)
    if site:  # docs.google.com is documentation even though google.com is ambiguous
        category, confidence = SITE_RULES[site]
        return Classification(category, confidence, ClassReason.SITE_RULE, ClassSource.RULE)
    return Classification(C.UNKNOWN, 0.0, ClassReason.NO_RULE, ClassSource.RULE)


def is_excluded(
    exe_name: str | None, domain: str | None, apps: frozenset[str], sites: frozenset[str]
) -> tuple[bool, bool]:
    """(program excluded, site excluded). A site is matched by hostname suffix."""
    app = bool(exe_name and exe_name in apps)
    site = bool(domain and suffix_match(domain, dict.fromkeys(sites)))
    return app, site


def effective(span: ActivitySpan, user: UserRules) -> Classification:
    """What reports show: the user's correction, then the user's rules (they also relabel
    earlier spans), then the classification stored at recording time."""
    if span.user_category:
        return Classification(
            span.user_category, 1.0, ClassReason.USER_CORRECTION, ClassSource.USER
        )
    if span.kind is SpanKind.ACTIVE and not span.excluded and (user.apps or user.sites):
        ruled = classify(span.kind, span.exe_name, span.domain, user=user)
        if ruled.source is ClassSource.USER_RULE:
            return ruled
    if span.category is not None:
        return Classification(
            span.category,
            span.confidence or 0.0,
            span.reason or ClassReason.NO_RULE,
            span.source or ClassSource.RULE,
        )
    return classify(span.kind, span.exe_name, span.domain, excluded=span.excluded)
