"""
Data processor: takes raw CSV rows from FCLM and returns structured summaries.
Formula: PT% = 100 - (Hours(Inferred) / Hours(Total) * 100)  -- BIN_TYPE PRIME + UNKNOWN
"""

def _f(v):
    try: return float(v)
    except: return 0.0

def process(rows):
    filtered = [r for r in rows if r.get('BIN_TYPE','').upper() in ('PRIME','UNKNOWN')]

    aa_map = {}
    for r in filtered:
        eid = r.get('Employee Id','').strip()
        if not eid: continue
        if eid not in aa_map:
            aa_map[eid] = {
                'id': eid,
                'name': r.get('Employee Name','').strip(),
                'manager': r.get('Manager Name','').strip(),
                'inferred': 0.0, 'total': 0.0,
            }
        aa_map[eid]['inferred'] += _f(r.get('Hours (Inferred)', 0))
        aa_map[eid]['total']    += _f(r.get('Hours (Total)',    0))

    associates = []
    for aa in aa_map.values():
        pt = round(100 - (aa['inferred'] / aa['total'] * 100), 1) if aa['total'] > 0 else None
        associates.append({**aa, 'pt': pt,
                           'inferred': round(aa['inferred'], 2),
                           'total':    round(aa['total'],    2)})

    mg_map = {}
    for aa in associates:
        m = aa['manager']
        if m not in mg_map:
            mg_map[m] = {'name': m, 'inferred': 0.0, 'total': 0.0, 'associates': []}
        mg_map[m]['inferred']   += aa['inferred']
        mg_map[m]['total']      += aa['total']
        mg_map[m]['associates'].append(aa)

    managers = []
    for mg in mg_map.values():
        pt = round(100 - (mg['inferred'] / mg['total'] * 100), 1) if mg['total'] > 0 else None
        managers.append({
            'name': mg['name'], 'pt': pt,
            'inferred': round(mg['inferred'], 2),
            'total':    round(mg['total'],    2),
            'aa_count': len(mg['associates']),
            'flagged':  sum(1 for a in mg['associates'] if a['pt'] is not None and a['pt'] < 84),
            'associates': sorted(mg['associates'], key=lambda a: a['pt'] or 99),
        })
    managers.sort(key=lambda m: m['pt'] or 0, reverse=True)

    valid = [a for a in associates if a['pt'] is not None]
    all_inf = sum(a['inferred'] for a in associates)
    all_tot = sum(a['total']    for a in associates)
    overall = round(100 - (all_inf / all_tot * 100), 1) if all_tot > 0 else 0.0

    return {
        'associates': sorted(associates, key=lambda a: a['pt'] or 99),
        'managers':   managers,
        'overall_pt': overall,
        'aa_count':   len(valid),
        'flagged':    sum(1 for a in valid if a['pt'] < 84),
        'above_90':   sum(1 for a in valid if a['pt'] >= 90),
        'total_inferred': round(all_inf, 1),
        'total_hours':    round(all_tot, 1),
    }
