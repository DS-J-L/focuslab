import pytest

from focuslab.activity.classifier import UserRules, classify, effective, is_excluded
from focuslab.domain.activity import ActivitySpan, Category, ClassReason, ClassSource, SpanKind

A, IDLE, LOCKED = SpanKind.ACTIVE, SpanKind.IDLE, SpanKind.LOCKED


@pytest.mark.parametrize("exe,category", [
    ("code.exe", Category.DEVELOPMENT),
    ("pycharm64.exe", Category.DEVELOPMENT),
    ("windowsterminal.exe", Category.DEVELOPMENT),
    ("winword.exe", Category.DOCUMENTATION),
    ("hwp.exe", Category.DOCUMENTATION),
    ("excel.exe", Category.PRODUCTIVITY),
    ("kakaotalk.exe", Category.COMMUNICATION),
    ("slack.exe", Category.COMMUNICATION),
    ("spotify.exe", Category.ENTERTAINMENT),
    ("steam.exe", Category.GAMING),
])
def test_programs_from_the_built_in_rules(exe, category):
    result = classify(A, exe)
    assert result.category is category and result.source is ClassSource.RULE
    assert result.reason is ClassReason.APP_RULE and 0 < result.confidence < 1


def test_games_are_recognized_by_their_library_folder():
    result = classify(A, "eldenring.exe", game_library=True)
    assert result.category is Category.GAMING and result.reason is ClassReason.GAME_LIBRARY


def test_lock_and_idle_are_break_with_full_confidence():
    for kind, reason in ((IDLE, ClassReason.IDLE), (LOCKED, ClassReason.LOCKED)):
        result = classify(kind, None)
        assert (result.category, result.reason, result.confidence, result.source) == (
            Category.BREAK, reason, 1.0, ClassSource.SYSTEM
        )


@pytest.mark.parametrize("domain,category,reason", [
    ("github.com", Category.DEVELOPMENT, ClassReason.SITE_RULE),
    ("gist.github.com", Category.DEVELOPMENT, ClassReason.SITE_RULE),
    ("ko.wikipedia.org", Category.RESEARCH, ClassReason.SITE_RULE),
    ("docs.google.com", Category.DOCUMENTATION, ClassReason.SITE_RULE),  # not "google.com"
    ("mail.naver.com", Category.COMMUNICATION, ClassReason.SITE_RULE),  # not "naver.com"
    ("netflix.com", Category.ENTERTAINMENT, ClassReason.SITE_RULE),
    ("youtube.com", Category.UNKNOWN, ClassReason.AMBIGUOUS_SITE),  # lectures and fun alike
    ("m.youtube.com", Category.UNKNOWN, ClassReason.AMBIGUOUS_SITE),
    ("google.com", Category.UNKNOWN, ClassReason.AMBIGUOUS_SITE),
    ("some-unknown-site.dev", Category.UNKNOWN, ClassReason.NO_RULE),
])
def test_sites_inside_a_browser(domain, category, reason):
    result = classify(A, "chrome.exe", domain)
    assert (result.category, result.reason) == (category, reason)


def test_uncertain_cases_stay_unknown():
    assert classify(A, "chrome.exe").reason is ClassReason.BROWSER_NO_SITE
    assert classify(A, "msedge.exe").category is Category.UNKNOWN
    assert classify(A, "vlc.exe").reason is ClassReason.AMBIGUOUS_APP
    assert classify(A, "explorer.exe").reason is ClassReason.NEUTRAL_SHELL
    assert classify(A, "focuslab").reason is ClassReason.NEUTRAL_SHELL
    assert classify(A, None).reason is ClassReason.UNREADABLE_APP
    assert classify(A, "mystery.exe").reason is ClassReason.NO_RULE
    for result in (classify(A, "chrome.exe"), classify(A, "mystery.exe")):
        assert result.confidence == 0.0


def test_user_rules_override_built_in_rules():
    rules = UserRules({"chrome.exe": Category.STUDY, "steam.exe": Category.BREAK},
                      {"youtube.com": Category.STUDY})
    assert classify(A, "chrome.exe", "youtube.com", user=rules).category is Category.STUDY
    assert classify(A, "msedge.exe", "m.youtube.com", user=rules).source is ClassSource.USER_RULE
    assert classify(A, "steam.exe", user=rules).category is Category.BREAK
    assert classify(IDLE, "code.exe", user=rules).category is Category.BREAK  # still idle


def test_exclusions_match_programs_and_site_suffixes():
    apps, sites = frozenset({"keepass.exe"}), frozenset({"bank.com"})
    assert is_excluded("keepass.exe", None, apps, sites) == (True, False)
    assert is_excluded("chrome.exe", "online.bank.com", apps, sites) == (False, True)
    assert is_excluded("chrome.exe", "github.com", apps, sites) == (False, False)
    assert classify(A, None, excluded=True).reason is ClassReason.EXCLUDED


def test_effective_classification_precedence():
    stored = ActivitySpan(0, 1, A, "chrome.exe", domain="youtube.com", span_id=1,
                          category=Category.UNKNOWN, confidence=0.3,
                          reason=ClassReason.AMBIGUOUS_SITE, source=ClassSource.RULE)
    none = UserRules.empty()
    assert effective(stored, none).reason is ClassReason.AMBIGUOUS_SITE
    rule = UserRules({}, {"youtube.com": Category.STUDY})
    assert effective(stored, rule).category is Category.STUDY  # rules relabel past spans
    corrected = ActivitySpan(**{**stored.__dict__, "user_category": Category.ENTERTAINMENT})
    assert effective(corrected, rule).source is ClassSource.USER  # the span's own correction
    legacy = ActivitySpan(0, 1, A, "code.exe")  # recorded before classification existed
    assert effective(legacy, none).category is Category.DEVELOPMENT
    excluded = ActivitySpan(0, 1, A, None, excluded=True, category=Category.UNKNOWN,
                            reason=ClassReason.EXCLUDED, source=ClassSource.SYSTEM)
    assert effective(excluded, UserRules({}, {"x.com": Category.STUDY})).reason is (
        ClassReason.EXCLUDED
    )
