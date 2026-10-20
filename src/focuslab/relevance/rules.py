"""Rule-based task relevance: clear evidence only, everything else is left UNCERTAIN.

- A site with many uses (YouTube, search) is judged by its page title, never by its name.
- Notes, AI assistants and other work tools are never unrelated by name alone.
- Games and entertainment are POSSIBLY_UNRELATED only when nothing ties them to the goal.
- A low overlap is not evidence of deviation; the embedding and context layers may still
  find a relation the words do not show.
"""

import functools
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from focuslab.activity.classifier import AI_APPS, AI_SITES, classify, suffix_match
from focuslab.activity.windows_tracker import normalize
from focuslab.config import BROWSERS, NEUTRAL_APPS
from focuslab.domain.activity import Category, SpanKind
from focuslab.relevance.models import (
    RelevanceInput,
    RelevanceLevel,
    RelevanceReason,
    RelevanceSource,
    TaskRelevanceResult,
    uncertain,
)

_WORD = re.compile(r"[\w+#]+", re.UNICODE)
_HANGUL = re.compile(r"[가-힣]")
_NOTIFICATION_COUNT = re.compile(r"^\(\d+\+?\)\s*")  # "(3) title - YouTube"
_SEPARATORS = (" - ", " | ", " – ", " — ", " :: ", " · ")

# Words that say how, not what: a goal "데이터베이스 시험공부" is about databases.
GENERIC_TERMS = frozenset(
    {
        "공부", "시험공부", "학습", "작업", "하기", "준비", "과제", "숙제", "정리", "복습",
        "예습", "강의", "수업", "프로젝트", "기초", "입문", "실습", "시험", "보기", "읽기",
        "쓰기", "작성", "개발", "연습", "중", "및", "the", "a", "an", "of", "to", "for",
        "and", "in", "on", "with", "study", "studying", "learn", "learning", "work",
        "working", "project", "homework", "exam", "review", "practice", "basics", "intro",
        "introduction", "course", "lecture", "tutorial", "class", "my", "about",
    }
)
# Korean particles left on a noun ("데이터베이스를"); stripped only from Hangul words.
_PARTICLES = (
    "에서는", "으로는", "이라는", "에서", "으로", "에게", "까지", "부터", "이란", "라는",
    "처럼", "보다", "하는", "하기", "은", "는", "이", "가", "을", "를", "의", "에", "와",
    "과", "도", "로", "만",
)

# Seed aliases so common topics match across languages without the embedding model.
# Each key is a goal term; its aliases count as that term in a page title.
TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "증강현실": ("ar", "augmented", "ar foundation", "arcore", "arkit", "vuforia", "xr"),
    "가상현실": ("vr", "virtual reality", "xr", "oculus", "openxr"),
    "데이터베이스": ("database", "db", "dbms", "sql", "mysql", "postgresql", "정규화", "join"),
    "프로그래밍": ("programming", "coding", "코딩", "code", "python", "java", "javascript"),
    "코딩": ("coding", "programming", "프로그래밍", "code"),
    "알고리즘": ("algorithm", "algorithms", "백준", "leetcode", "코딩테스트"),
    "머신러닝": ("machine learning", "ml", "딥러닝", "deep learning", "pytorch", "tensorflow"),
    "인공지능": ("ai", "artificial intelligence", "머신러닝", "딥러닝", "machine learning"),
    "딥러닝": ("deep learning", "neural network", "신경망", "pytorch", "tensorflow"),
    "논문": ("paper", "arxiv", "research", "연구"),
    "운영체제": ("operating system", "os", "process", "프로세스", "스레드", "thread"),
    "네트워크": ("network", "networking", "tcp", "http", "네트워킹"),
    "자료구조": ("data structure", "data structures", "linked list", "트리", "tree"),
    "영어": ("english", "toeic", "토익", "토플", "toefl", "ielts"),
    "수학": ("math", "mathematics", "미적분", "calculus", "선형대수", "linear algebra"),
    "웹": ("web", "html", "css", "javascript", "react", "frontend", "프론트엔드"),
    "유니티": ("unity",),
    "unity": ("유니티",),
}

# Phrases that mark leisure viewing; matched as whole words in the cleaned title.
ENTERTAINMENT_MARKERS = (
    "게임 플레이", "게임플레이", "gameplay", "let's play", "하이라이트", "highlights",
    "예능", "먹방", "mukbang", "뮤직비디오", "music video", "official mv", "m/v", "직캠",
    "fancam", "드라마", "몰아보기", "리액션", "reaction", "웃긴", "funny", "브이로그", "vlog",
    "asmr", "배그", "롤토체스", "league of legends", "리그오브레전드", "매드무비", "명장면",
    "예고편", "trailer",
)
# Goals that make games or media part of the task (game design, film review...).
_MEDIA_GOAL_TERMS = frozenset(
    {
        "게임", "game", "games", "gaming", "영화", "movie", "film", "드라마", "음악", "music",
        "영상", "video", "방송", "stream", "유튜브", "youtube", "콘텐츠", "content", "마케팅",
        "marketing", "편집", "editing", "리뷰", "review",
    }
)
# Titles that only name the site or an empty tab.
_EMPTY_TITLES = frozenset(
    {
        "", "youtube", "new tab", "새 탭", "새탭", "google", "naver", "네이버", "daum", "bing",
        "home", "홈", "untitled", "제목 없음", "loading", "로딩 중",
    }
)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _strip_particle(word: str) -> str:
    if not _HANGUL.search(word):
        return word
    for particle in _PARTICLES:
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return word[: -len(particle)]
    return word


def words(text: str) -> list[str]:
    return [_strip_particle(w) for w in _WORD.findall(_nfc(text))]


def goal_terms(goal: str) -> tuple[str, ...]:
    """Content words of the goal, generic study and work words removed."""
    out = []
    for word in words(goal):
        if word in GENERIC_TERMS or len(word) < 2 and not word.isascii():
            continue
        for suffix in ("공부", "학습", "개발", "정리"):  # "데이터베이스공부" -> "데이터베이스"
            if word.endswith(suffix) and len(word) - len(suffix) >= 2:
                word = word[: -len(suffix)]
                break
        if word not in out:
            out.append(word)
    return tuple(out)


def clean_title(title: str, domain: str | None) -> str:
    """Drop notification counts and a trailing site name ("... - YouTube")."""
    text = _NOTIFICATION_COUNT.sub("", title.strip())
    brand = _nfc(domain.split(".")[-2]) if domain and "." in domain else None
    for sep in _SEPARATORS:
        head, found, tail = text.rpartition(sep)
        if found and head and brand and brand in _nfc(tail).replace(" ", ""):
            text = head
            break
    return text.strip()


@functools.lru_cache(maxsize=1024)
def _term(text: str) -> str:
    """A term normalized exactly like title words, so particle stripping cancels out."""
    return " ".join(words(text))


def _contains(haystack_words: list[str], joined: str, term: str) -> bool:
    """Whole-word match for Latin terms; Hangul terms also match inside compounds."""
    term = _term(term)
    if not term:
        return False
    if " " in term:
        return f" {term} " in f" {joined} "
    if _HANGUL.search(term):
        return any(term in w for w in haystack_words)
    return term in haystack_words or term.rstrip("s") in haystack_words


@dataclass(frozen=True)
class TitleMatch:
    matched: tuple[str, ...]  # goal terms found directly or through an alias
    terms: tuple[str, ...]

    @property
    def score(self) -> float:
        return len(self.matched) / len(self.terms) if self.terms else 0.0


def match_title(goal: str, title: str, aliases: dict[str, tuple[str, ...]] | None = None):
    aliases = TOPIC_ALIASES if aliases is None else aliases
    terms = goal_terms(goal)
    title_words = words(title)
    joined = " ".join(title_words)
    matched = tuple(
        term
        for term in terms
        if _contains(title_words, joined, term)
        or any(_contains(title_words, joined, a) for a in aliases.get(term, ()))
    )
    return TitleMatch(matched, terms)


def _has_marker(title: str, markers: Iterable[str]) -> bool:
    title_words = words(title)
    joined, raw = " ".join(title_words), _nfc(title)
    return any(
        m in raw if _WORD.fullmatch(m.replace(" ", "")) is None else _contains(
            title_words, joined, m
        )
        for m in markers
    )


def _goal_mentions_media(goal: str) -> bool:
    return any(t in _MEDIA_GOAL_TERMS for t in words(goal))


def _rule(level: RelevanceLevel, score: float | None, *reasons: str) -> TaskRelevanceResult:
    return TaskRelevanceResult(level, score, reasons, RelevanceSource.RULE)


def judge_title(data: RelevanceInput) -> TaskRelevanceResult:
    title = clean_title(data.page_title or "", data.domain)
    if _nfc(title) in _EMPTY_TITLES or len(title) < 3:
        return _rule(RelevanceLevel.UNCERTAIN, None, RelevanceReason.TITLE_UNINFORMATIVE)
    match = match_title(data.goal, title)
    leisure = _has_marker(title, ENTERTAINMENT_MARKERS)
    if match.matched and leisure:  # "게임 기획" vs. a gameplay compilation
        return _rule(RelevanceLevel.UNCERTAIN, match.score, RelevanceReason.TITLE_MIXED_SIGNALS)
    if match.matched:
        return _rule(RelevanceLevel.RELATED, match.score, RelevanceReason.TITLE_MATCHES_GOAL)
    if leisure and not _goal_mentions_media(data.goal):
        return _rule(RelevanceLevel.POSSIBLY_UNRELATED, 0.0, RelevanceReason.TITLE_ENTERTAINMENT)
    return _rule(RelevanceLevel.UNCERTAIN, match.score, RelevanceReason.NO_EVIDENCE)


def judge(data: RelevanceInput) -> TaskRelevanceResult:
    """Judge one activity against the goal; the caller has checked the input is usable."""
    name = normalize(data.process_name or "")
    if name in NEUTRAL_APPS:  # desktop shell, task switcher, FocusLab: in passing, not work
        return _rule(RelevanceLevel.UNCERTAIN, None, RelevanceReason.NEUTRAL_APP)
    if name in AI_APPS or (data.domain and suffix_match(data.domain, AI_SITES)):
        return _rule(RelevanceLevel.UNCERTAIN, None, RelevanceReason.SUPPORT_TOOL)
    category = classify(SpanKind.ACTIVE, name, data.domain).category
    leisure = category in (Category.ENTERTAINMENT, Category.GAMING)
    if data.page_title:
        result = judge_title(data)
        if result.level is not RelevanceLevel.UNCERTAIN:
            return result
    if leisure and not _goal_mentions_media(data.goal):
        return _rule(RelevanceLevel.POSSIBLY_UNRELATED, 0.0, RelevanceReason.ENTERTAINMENT_ACTIVITY)
    if data.page_title:
        return result
    if data.domain or name in BROWSERS:
        return uncertain(RelevanceReason.TITLE_UNAVAILABLE)
    if category in (Category.DOCUMENTATION, Category.PRODUCTIVITY):
        return _rule(RelevanceLevel.UNCERTAIN, None, RelevanceReason.SUPPORT_TOOL)
    if category is Category.COMMUNICATION:
        return _rule(RelevanceLevel.UNCERTAIN, None, RelevanceReason.COMMUNICATION)
    return _rule(RelevanceLevel.UNCERTAIN, None, RelevanceReason.NO_EVIDENCE)
