# statusline

A Claude Code status line showing model, working directory/git branch, context
window usage, and Pro/Max plan rate limits (5-hour and 7-day windows).

```
[Sonnet 5] | my-project (main +2~1) | ctx ████░░░░░░ 42% (84.6k/200k) | 5h 24% (resets 2h13m) | 7d 91% (resets Mon 16:52) | effort: high
```

Colors shift green → yellow → red at 70% / 90% usage for both the context bar
and the rate-limit segments.

## Install

Requires Python 3.

```bash
chmod +x statusline.py
```

Add to `~/.claude/settings.json` (all sessions) or this project's
`.claude/settings.json` (this project only):

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /Users/abrown/git/statusline/statusline.py"
  }
}
```

## Notes

- `ctx`, `5h`, and `7d` always render, even before Claude Code has sent real
  data. Until the first API response of a session completes, they show a
  `--%` placeholder instead of disappearing.
- `rate_limits` is only ever sent for Claude.ai Pro/Max subscribers. On
  API-key or unsupported sessions, `5h`/`7d` will show `--%` for the entire
  session, since that data never arrives — this is expected, not a bug.
- `effort` is omitted when the current model doesn't support the reasoning
  effort parameter.
- There is no field for "extra usage" / usage-credits balance in the status
  line JSON — Claude Code only exposes `rate_limits.five_hour` and
  `rate_limits.seven_day`. Credit usage isn't shown here; check `/usage-credits`.
- Git branch/status lookups are cached per session for 5 seconds to keep the
  status line responsive in large repos.
- Test changes with mock input before wiring it into settings:
  ```bash
  echo '{"model":{"display_name":"Sonnet 5"},"workspace":{"current_dir":"'"$PWD"'"},"context_window":{"used_percentage":25},"session_id":"test"}' | python3 statusline.py
  ```
