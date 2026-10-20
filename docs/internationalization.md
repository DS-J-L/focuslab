# Interface localization

FocusLab supports English (`en`) and Korean (`ko`). Repository documentation is maintained in English.

## User controls

- First launch follows the system locale: Korean for `ko`, English otherwise.
- Settings > Appearance > Language stores `ui.language` in the local settings table. Restart to apply it; a selection does not interrupt sessions or discard unsaved forms.
- `focuslab --language en|ko` or `FOCUSLAB_LANGUAGE=en|ko` overrides the saved choice for that run.
- English/Korean choices are shown using their native language names so either audience can find them.
- UI labels, dialogs, evidence descriptions, category/state names, tray menus, and durations are localized. Technical CLI diagnostics retain English. Qt's shipped translations cover standard dialog buttons when available; native system dialogs can follow the OS language.

## Message conventions

`src/focuslab/i18n.py` is the single translation entry point. English source text is the message ID; `src/focuslab/locales/ko.json` maps it to Korean. The catalog is shipped inside the Python package, and English is the fallback for an unknown message.

```python
from focuslab.i18n import tr

button.setText(tr("Start focus session"))
label.setText(tr("Saved:\n{p0}", p0=path))
```

Translate a complete message before formatting named placeholders. Keep placeholders and their conversions/format specs compatible in both languages. Values such as goals, app names, domains, and paths are user/data content and are never translated. Avoid assembling translatable sentences from fragments.

For module-level label dictionaries, use `LocalizedMapping` so labels resolve when accessed rather than when the module is imported:

```python
from focuslab.i18n import LocalizedMapping

LABELS = LocalizedMapping({"FINISHED": "Completed", "RUNNING": "In progress"})
```

Keys remain stable. Combo boxes store enums, language codes, or numeric durations as `userData`; translated display text must not be used to identify a report range or stored state. Use `weekday_name` rather than indexing English/Korean text by character. Duration formatting is shared in `focus/metrics.py`.

## Persistence and thread behavior

The active language is initialized before building pages. Changing the preference writes only the setting; it does not rebuild a live window or change the active process language. Report workers therefore use the same language throughout a run. On restart, lazy label dictionaries resolve in the newly selected language.

No database schema migration is needed. Existing sessions, observations, goal text, classification/evidence codes, and machine-readable export keys are unchanged. Export explanations and human-readable fallback labels may follow the interface language.

## Validation

```powershell
uv run pytest tests/unit/test_i18n.py tests/e2e/test_languages.py
uv run focuslab --demo --language en
uv run focuslab --demo --language ko
uv build
```

Check catalog placeholder compatibility, language precedence/fallback, saved preference across contexts, menus and all five pages, onboarding/consent/calibration, reports with data, and wheel inclusion of `locales/ko.json`. Screenshots must use synthetic data and no real camera footage.
