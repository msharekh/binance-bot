"""Entry-time strategy checks, shared by the bot and trade cards."""

from html import escape


ENTRY_CHECKS = (
    ("rsi_recovered", "RSI", "RSI recovery"),
    ("near_support", "SUP", "Near support"),
    ("trend_ok", "TREND", "Higher-timeframe EMA trend"),
    ("reward_ok", "REWARD", "Minimum expected net reward"),
    ("stop_risk_ok", "RISK", "Maximum stop distance"),
    ("momentum_ok", "9/21", "EMA 9 > EMA 21"),
)


def capture_entry_conditions(analysis):
    return {
        key: bool(analysis[key]) if analysis.get(key) is not None else None
        for key, _, _ in ENTRY_CHECKS
    }


def entry_conditions_html(position, market=None):
    live = market is not None
    checks = market if live else (position.get("entry_conditions") or {})
    badges = []
    for key, label, description in ENTRY_CHECKS:
        value = checks.get(key)
        color, mark, state = (
            ("#22c55e", "&#10003;", "Met at entry") if value is True else
            ("#ef4444", "&#215;", "Not met at entry") if value is False else
            ("#94a3b8", "?", "Not recorded at entry")
        )
        if live:
            state = (
                "Met in latest analysis" if value is True else
                "Not met in latest analysis" if value is False else
                "Not available in latest analysis"
            )
        title = escape(f"{description}: {state}", quote=True)
        badges.append(
            f'<span title="{title}" aria-label="{title}" style="display:inline-flex;'
            'align-items:center;gap:4px;white-space:nowrap">'
            f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:15px;height:15px;border-radius:50%;background:{color};'
            f'color:#0f172a;font-size:11px;font-weight:700">{mark}</span>'
            f'{label}</span>'
        )
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:6px 10px;'
        'align-items:center;font-size:11px;margin:6px 0">'
        + ('<span style="color:#94a3b8" title="Updates with completed-candle analysis">Current conditions</span>'
           if live else '<span style="color:#94a3b8">At entry</span>')
        + "".join(badges) + '</div>'
    )
