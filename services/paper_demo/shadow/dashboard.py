"""Local static dashboard. Contains simulated results only; no scripts or external assets."""
from html import escape
from pathlib import Path
import json


def write_dashboard(directory: Path):
    reports = [json.loads(line) for line in (directory/'reports.jsonl').read_text().splitlines()]
    latest = {}
    for report in reports:
        latest[report['ticker']] = report
    values = list(latest.values())
    if not values:
        return
    current = values[-1]
    def value(key, prefix='', suffix=''):
        x=current.get(key)
        return 'Pending' if x is None else escape(prefix+str(x)+suffix)
    cards = [('Win rate',value('win_rate',suffix='%')),
             ('Gross profit',value('gross_profit',prefix='$')),
             ('Total fees paid',value('total_fees_paid',prefix='$')),
             ('Avg slippage / taker order',value('average_slippage_per_taker_order',prefix='$')),
             ('Net realized PnL',value('net_realized_pnl',prefix='$')),
             ('Virtual cash',value('cash',prefix='$'))]
    card_html=''.join(f'<article><span>{escape(label)}</span><strong>{number}</strong></article>'
                      for label,number in cards)
    rows=''.join('<tr>'+''.join(f'<td>{escape(str(x))}</td>' for x in (
        r['ticker'],'Settled' if r['final'] else 'Awaiting settlement',
        'Valid' if r['data_valid'] else 'EXCLUDED: data gap',r['open_contracts'],
        '$'+r['gross_profit'],'$'+r['total_fees_paid'],'$'+r['net_realized_pnl'],
        r['stress_fill_contracts']))+'</tr>' for r in reversed(values[-30:]))
    warning = ('<p class="warning">SYNTHETIC VALIDATION: fabricated prices. These are not market performance results.</p>'
               if any('SYNTHETIC' in r['ticker'] for r in values) else '')
    status = 'Settled' if current['final'] else 'Cycle closed • settlement pending'
    valid = 'Data valid' if current['data_valid'] else 'EXCLUDED — feed gap or unsupported data'
    html=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="5"><title>Money Tree · Shadow Trading</title>
<style>body{{margin:0;background:#10151c;color:#e9f0f5;font:16px system-ui,sans-serif}}main{{max-width:1240px;margin:auto;padding:32px}}h1{{font-size:38px;margin:8px 0}}h2{{margin-top:32px}}.eyebrow{{color:#97e2bb;font-weight:700;letter-spacing:.1em}}.muted,article span{{color:#a9b9c8}}.warning{{padding:16px;background:#573f14;border-radius:12px}}.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:26px 0}}article{{background:#1a2430;border:1px solid #304050;border-radius:14px;padding:22px}}article strong{{display:block;font-size:28px;margin-top:8px;overflow-wrap:anywhere}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;white-space:nowrap}}td,th{{padding:14px;border-bottom:1px solid #304050;text-align:left}}th{{color:#a9b9c8}}@media(max-width:700px){{main{{padding:20px}}h1{{font-size:30px}}.cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}article{{padding:16px}}article strong{{font-size:22px}}}}</style>
<main><div class="eyebrow">MONEY TREE</div><h1>SHADOW · VIRTUAL MONEY</h1>
<p class="muted">Production market data. Simulated orders only. No real funds move.</p>{warning}
<h2>{escape(current['ticker'])}</h2><p>{escape(status)} · {escape(valid)}</p>
<div class="cards">{card_html}</div>
<p class="muted">Open contracts: {value('open_contracts')} · Stress-mode filled contracts: {value('stress_fill_contracts')} · Available virtual cash: ${value('available_cash')}</p>
<h2>Cycle history</h2><div class="scroll"><table><thead><tr><th>Market</th><th>Status</th><th>Data quality</th><th>Open</th><th>Gross</th><th>Fees</th><th>Net realized</th><th>Stress fills</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted">Win rate is weighted by closed contract quantity. Slippage is measured from decision-time quotes and may include favorable moves. Open positions are excluded from realized PnL until closed or settled. Cycles marked EXCLUDED must not be used as strategy evidence.</p>
<p class="muted">This page refreshes every five seconds. Audit detail: events.csv · reports.jsonl · ledger.sqlite3.</p></main></html>'''
    temporary=directory/'.dashboard.tmp'
    temporary.write_text(html)
    temporary.replace(directory/'dashboard.html')
