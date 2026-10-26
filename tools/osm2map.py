#!/usr/bin/env python3
"""OpenStreetMap -> mapa de tiles estil Pokémon (Plaça de la Vila, Vilanova i la Geltrú).

Ús:
  python3 tools/osm2map.py --fetch   # baixa osm.json d'Overpass i genera map.js
  python3 tools/osm2map.py           # genera map.js a partir de l'osm.json desat
  python3 tools/osm2map.py --test    # comprovacions mínimes

Mètode (calle a calle, sense col·locar res a ull):
  1. Projecció local en metres centrada al monument i girada perquè l'eix
     Ajuntament -> Biblioteca quedi cap amunt (al joc: Ajuntament al sud).
  2. Rasteritzat a una graella de S metres per tile, per capes:
     terrats -> edificis -> carrers -> plaça -> passatges dels porxos.
     Abans, tota la geometria s'encaixa a línies horitzontals/verticals (manhattan).
  3. Regla Pokémon: cada edifici mostra la façana a la fila de baix si a sota
     s'hi pot caminar; la resta és terrat.
  4. Objectes puntuals (arbres, bancs, fanals, terrasses, monument) i rètols de
     botigues/bars sobre la façana de l'edifici on són.
Dades: © OpenStreetMap contributors (ODbL).
"""
import json, math, os, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OSM = os.path.join(HERE, 'osm.json')
OUT = os.path.join(HERE, '..', 'map.js')
BBOX = (41.2222, 1.7238, 41.2262, 1.7284)
S = 3.5    # metres per tile. ponytail: escala única; Pokémon comprimeix distàncies, ajustar a ull si cal
R = 105    # radi (m) de l'àrea generada al voltant del monument
N = int(2 * R / S) // 2 * 2   # mida de la graella (parell, monument al centre)
WIDTH = {'living_street': 6, 'residential': 7, 'service': 4, 'pedestrian': 5, 'footway': 3, 'steps': 3}


def fetch():
    q = f'[out:json][timeout:60];(way{BBOX};node{BBOX};relation{BBOX};);out body;>;out skel qt;'
    data = urllib.parse.urlencode({'data': q}).encode()
    req = urllib.request.Request('https://overpass-api.de/api/interpreter', data, {'User-Agent': 'poke-vilanova'})
    with urllib.request.urlopen(req, timeout=90) as r, open(OSM, 'wb') as f:
        f.write(r.read())


def rings_of(rel, ways):
    """Uneix els membres d'un multipolígon en anells tancats (llistes d'ids de node)."""
    segs = [list(ways[m['ref']]['nodes']) for m in rel['members'] if m['type'] == 'way' and m['ref'] in ways]
    rings = []
    while segs:
        ring = segs.pop()
        while ring[0] != ring[-1]:
            for i, s in enumerate(segs):
                if s[0] == ring[-1]: ring += s[1:]
                elif s[-1] == ring[-1]: ring += s[-2::-1]
                elif s[-1] == ring[0]: ring = s[:-1] + ring
                elif s[0] == ring[0]: ring = s[:0:-1] + ring
                else: continue
                segs.pop(i); break
            else: break   # anell obert: el deixem tal qual
        rings.append(ring)
    return rings


def inside(pt, rings):
    """Parell-senar sobre tots els anells (serveix per a forats interiors)."""
    x, y = pt; c = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: c = not c
    return c


def seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = 0 if dx == dy == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def simplify(pts, tol):
    """Douglas-Peucker: índexs dels punts que es queden."""
    if len(pts) < 3: return list(range(len(pts)))
    d, k = max((seg_dist(pts[i], pts[0], pts[-1]), i) for i in range(1, len(pts) - 1))
    if d <= tol: return [0, len(pts) - 1]
    return simplify(pts[:k + 1], tol)[:-1] + [k + j for j in simplify(pts[k:], tol)]


def manhattan(lists, pos, tol=.6, slope=math.tan(math.radians(25)), near=.7):
    """Encaixa la xarxa a línies horitzontals i verticals (estil Pokémon).

    Trams gairebé horitzontals/verticals s'agrupen (si comparteixen node o són a
    tocar) i s'alineen a una mateixa coordenada entera; la resta queda en L.
    Retorna {node: (x, y)}.
    """
    segs = {0: [], 1: []}                              # 0: horitzontal (fixa y), 1: vertical (fixa x)
    for ids in lists:
        ids = [i for i in ids if i in pos]
        keep = simplify([pos[i] for i in ids], tol)
        for a, b in zip(keep, keep[1:]):
            (ax, ay), (bx, by) = pos[ids[a]], pos[ids[b]]
            dx, dy = abs(bx - ax), abs(by - ay)
            if dy <= slope * dx: segs[0].append((ids[a], ids[b]))
            elif dx <= slope * dy: segs[1].append((ids[a], ids[b]))
    snap = {i: list(p) for i, p in pos.items()}
    for ax in (0, 1):
        fix, run = 1 - ax, ax                          # coordenada que fixem / coordenada al llarg
        ss = segs[ax]; par = list(range(len(ss)))
        def find(i):
            while par[i] != i: par[i] = par[par[i]]; i = par[i]
            return i
        val = [(pos[a][fix] + pos[b][fix]) / 2 for a, b in ss]
        rng = [sorted((pos[a][run], pos[b][run])) for a, b in ss]
        by_node = {}
        for k, (a, b) in enumerate(ss):
            for n in (a, b):
                if n in by_node and abs(val[by_node[n]] - val[k]) < 1.5: par[find(k)] = find(by_node[n])
                by_node.setdefault(n, k)
        order = sorted(range(len(ss)), key=lambda k: val[k])
        for i, k in enumerate(order):                  # parets/carrers paral·lels a tocar -> mateixa línia
            for j in order[i + 1:]:
                if val[j] - val[k] > near: break
                if rng[j][0] <= rng[k][1] + 1 and rng[k][0] <= rng[j][1] + 1: par[find(j)] = find(k)
        tot = {}
        for k, (a, b) in enumerate(ss):
            w = rng[k][1] - rng[k][0] + .1; t = tot.setdefault(find(k), [0, 0]); t[0] += w * val[k]; t[1] += w
        best = {}                                      # node -> (pes, valor) del grup més llarg que hi toca
        for k, (a, b) in enumerate(ss):
            w, v = tot[find(k)][1], round(tot[find(k)][0] / tot[find(k)][1])
            for n in (a, b):
                if w > best.get(n, (0,))[0]: best[n] = (w, v)
        for n, (_, v) in best.items(): snap[n][fix] = v
    return {i: tuple(p) for i, p in snap.items()}


def build(elements):
    # Overpass repeteix elements (out body + out skel): ens quedem amb la versió que té etiquetes
    pick = lambda t: {e['id']: e for e in sorted((e for e in elements if e['type'] == t), key=lambda e: bool(e.get('tags')))}
    nodes = {k: e for k, e in pick('node').items() if 'lat' in e}
    ways = pick('way')
    rels = [e for e in elements if e['type'] == 'relation']
    tag = lambda e: e.get('tags', {})

    mon = next(w for w in ways.values() if tag(w).get('name', '').startswith('Monument a Josep Tom'))
    town = next(n for n in nodes.values() if tag(n).get('amenity') == 'townhall')
    lib = next(w for w in ways.values() if tag(w).get('amenity') == 'library')
    lat0 = sum(nodes[i]['lat'] for i in mon['nodes']) / len(mon['nodes'])
    lon0 = sum(nodes[i]['lon'] for i in mon['nodes']) / len(mon['nodes'])
    kx, ky = 111320 * math.cos(math.radians(lat0)), 111320

    def en(n): return ((n['lon'] - lon0) * kx, (n['lat'] - lat0) * ky)
    # eix Ajuntament -> Biblioteca = amunt
    lc = [en(nodes[i]) for i in lib['nodes']]
    te = en(town)
    up = math.atan2(sum(p[1] for p in lc) / len(lc) - te[1], sum(p[0] for p in lc) / len(lc) - te[0])
    # graella alineada amb els costats de la plaça (estil Pokémon: tot ortogonal).
    # Els costats reals no fan 90° exactes: fem servir una base afí perquè quedin rectes tots dos.
    isp = lambda e: tag(e).get('name') == 'Plaça de la Vila' and tag(e).get('highway') == 'pedestrian'
    pr = max([[w['nodes']] for w in ways.values() if isp(w) and w['nodes'][0] == w['nodes'][-1]] +
             [rings_of(r, ways) for r in rels if isp(r)], key=lambda r: sum(map(len, r)))   # el polígon més complet
    edges = [(en(nodes[a]), en(nodes[b])) for r in pr for a, b in zip(r, r[1:]) if a in nodes and b in nodes]
    bases = []
    for ref in (up, up + math.pi / 2):                 # direcció "amunt" i "dreta" dominants
        sx = sy = 0
        for (ax, ay), (bx, by) in edges:
            d = math.hypot(bx - ax, by - ay); a = math.atan2(by - ay, bx - ax)
            if math.cos(2 * (a - ref)) > .8:           # costat paral·lel a ref (±18°)
                sx += d * math.cos(2 * a); sy += d * math.sin(2 * a)
        a = math.atan2(sy, sx) / 2
        if math.cos(a - ref) < 0: a += math.pi
        bases.append((math.cos(a), math.sin(a)))
    (ux, uy), (vx, vy) = bases[0], bases[1]
    if vx * math.cos(up - math.pi / 2) + vy * math.sin(up - math.pi / 2) < 0: vx, vy = -vx, -vy   # dreta = sentit horari
    det = vx * uy - vy * ux

    def g(n):                                          # node -> coordenades del joc en tiles
        e, nn = en(n)                                  # e = a*v + b*u  ->  resolem a (dreta) i b (amunt)
        a, b = (e * uy - nn * ux) / det, (vx * nn - vy * e) / det
        return (a / S + N / 2, -b / S + N / 2)

    snap = manhattan([w['nodes'] for w in ways.values()] + [rg for r in rels for rg in rings_of(r, ways)],
                     {i: g(n) for i, n in nodes.items()})

    def poly(ids):                                     # geometria encaixada a la quadrícula (només trams rectes)
        pts = [snap[i] for i in ids if i in snap]
        out = pts[:1]
        for b in pts[1:]:
            a = out[-1]
            if a[0] != b[0] and a[1] != b[1]: out.append((b[0], a[1]))   # tram en diagonal -> L
            out.append(b)
        return out

    grid = [['b'] * N for _ in range(N)]
    owner = [[None] * N for _ in range(N)]             # edifici de cada cel·la

    def fill_rings(rings, fn):
        pts = [p for r in rings for p in r]
        if not pts: return
        x0, x1 = max(0, int(min(p[0] for p in pts))), min(N - 1, int(max(p[0] for p in pts)))
        y0, y1 = max(0, int(min(p[1] for p in pts))), min(N - 1, int(max(p[1] for p in pts)))
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if inside((x + .5, y + .5), rings): fn(x, y)

    def fill_line(ids, width, fn):
        pts = poly(ids); hw = max(width / 2 / S, .5)
        for a, b in zip(pts, pts[1:]):
            for y in range(max(0, int(min(a[1], b[1]) - hw - 1)), min(N, int(max(a[1], b[1]) + hw + 2))):
                for x in range(max(0, int(min(a[0], b[0]) - hw - 1)), min(N, int(max(a[0], b[0]) + hw + 2))):
                    if seg_dist((x + .5, y + .5), a, b) <= hw: fn(x, y)

    def setc(c):
        def f(x, y): grid[y][x] = c
        return f

    areas = [(w, [poly(w['nodes'])]) for w in ways.values() if w['nodes'][0] == w['nodes'][-1]]
    areas += [(r, [poly(rg) for rg in rings_of(r, ways)]) for r in rels if tag(r).get('type') == 'multipolygon']

    # 1. edificis (els carrers hi passen per sobre: després d'encaixar a la quadrícula se solapen)
    kinds = {}
    for e, rg in areas:
        t = tag(e)
        if t.get('building') and t['building'] not in ('roof',) and 'building:part' not in t:
            kind = 'lib' if e is lib else 'gen'
            def mark(x, y, e=e, kind=kind):
                grid[y][x] = 'B'; owner[y][x] = e['id']; kinds[e['id']] = kind
            fill_rings(rg, mark)
    tx, ty = map(int, g(town))                         # edifici de l'Ajuntament: el que conté el node
    town_id = owner[ty][tx]
    if town_id: kinds[town_id] = 'town'
    # 2. carrers (àrees i línies)
    for e, rg in areas:
        if tag(e).get('highway') in ('pedestrian', 'living_street', 'footway') and tag(e).get('area') == 'yes':
            fill_rings(rg, setc('r'))
    for w in ways.values():
        t = tag(w)
        if t.get('highway') in WIDTH and t.get('area') != 'yes' and 'tunnel' not in t and t.get('layer', '0') == '0':
            fill_line(w['nodes'], WIDTH[t['highway']], setc('r'))
    # 3. la plaça
    plaza = next(rg for e, rg in areas if tag(e).get('name') == 'Plaça de la Vila' and tag(e).get('highway') == 'pedestrian')
    fill_rings(plaza, setc('.'))
    # 4. porxos: passatges sota els edificis
    for w in ways.values():
        if tag(w).get('tunnel') == 'building_passage':
            fill_line(w['nodes'], 4, setc('p'))

    walk = lambda x, y: 0 <= x < N and 0 <= y < N and grid[y][x] in '.rp'
    # tires d'edifici d'1 fila entre dues zones de pas (escales, voladissos): fora, queden lletges en vista zenital
    for y in range(1, N - 1):
        for x in range(N):
            if grid[y][x] == 'B' and walk(x, y - 1) and walk(x, y + 1):
                grid[y][x] = '.' if '.' in (grid[y - 1][x], grid[y + 1][x]) else 'r'
    # porxos d'1 sola fila: si en fan 2 de cara a la plaça (línia encaixada entre dues files), la de fora és plaça
    pre = [row[:] for row in grid]
    for y in range(1, N - 1):
        for x in range(1, N - 1):
            if pre[y][x] == 'p' and any(pre[y + dy][x + dx] == '.' and pre[y - dy][x - dx] == 'p'
                                        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                grid[y][x] = '.'
    # columnes dels porxos al costat de la plaça
    for y in range(N):
        for x in range(N):
            if grid[y][x] == 'p' and any(0 <= y + dy < N and 0 <= x + dx < N and grid[y + dy][x + dx] == '.'
                                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))) and (x + y) % 3 == 0:
                grid[y][x] = 'a'
    # vora de la plaça: franja de paviment llis
    pre = [row[:] for row in grid]                     # sense cascada: mirem l'estat d'abans
    for y in range(N):
        for x in range(N):
            if pre[y][x] == '.' and any(not (0 <= y + dy < N and 0 <= x + dx < N) or pre[y + dy][x + dx] not in '.'
                                         for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                grid[y][x] = 'e'
    # 5. façanes (regla Pokémon): fila de baix = planta baixa, la de sobre = pis
    FAC = {'gen': ('F', 'f', 'b'), 'lib': ('K', 'l', 'b'), 'town': ('R', 'R', 'R')}
    snapshot = [row[:] for row in grid]
    for y in range(N):
        for x in range(N):
            if snapshot[y][x] != 'B': continue
            k = FAC[kinds.get(owner[y][x], 'gen')]
            below = snapshot[y + 1][x] if y + 1 < N else 'b'
            below2 = snapshot[y + 2][x] if y + 2 < N else 'b'
            grid[y][x] = k[0] if below in '.rpae' else k[1] if below == 'B' and below2 in '.rpae' else k[2]

    # 6. objectes
    pois, labels = [], {}
    mx, my = N // 2 - 1, N // 2 - 1                    # monument 2x2 al centre
    for dx in (0, 1):
        for dy in (0, 1): grid[my + dy][mx + dx] = 'm'
    in_plaza = lambda x, y: snapshot[y][x] in '.e'
    for n in nodes.values():
        t = tag(n)
        x, y = map(int, g(n))
        if not (0 <= x < N and 0 <= y < N): continue
        if t.get('natural') == 'tree' and grid[y][x] in '.er':
            grid[y][x] = 'P' if in_plaza(x, y) else 'T'
        elif t.get('amenity') == 'bench' and grid[y][x] in '.er': grid[y][x] = 'n'
        elif t.get('highway') == 'street_lamp' and grid[y][x] in '.er': grid[y][x] = 'L'
        name = t.get('name')
        if name and (t.get('amenity') or t.get('shop') or t.get('office') or t.get('craft')) and t.get('amenity') != 'townhall':
            # rètol a la façana (planta baixa) més propera
            best = min(((abs(fx - x) + abs(fy - y), fx, fy) for fy in range(max(0, y - 4), min(N, y + 5))
                        for fx in range(max(0, x - 4), min(N, x + 5)) if grid[fy][fx] in 'FK'), default=None)
            if best and f'{best[1]},{best[2]}' not in labels:
                kind = t.get('amenity') or t.get('shop') or t.get('office') or t.get('craft')
                labels[f'{best[1]},{best[2]}'] = [name, kind]
    for e, rg in areas:                                 # terrasses
        if tag(e).get('leisure') == 'outdoor_seating':
            def tab(x, y):
                if grid[y][x] in '.e' and (x + y) % 2 == 0: grid[y][x] = 't'
            fill_rings(rg, tab)

    # noms de carrers per mostrar el rètol en entrar-hi
    names = ['Plaça de la Vila']
    zone = [[0 if snapshot[y][x] in '.e' else -1 for x in range(N)] for y in range(N)]
    def zone_fill(nm):
        if nm not in names: names.append(nm)
        i = names.index(nm)
        def f(x, y):
            if zone[y][x] == -1 and grid[y][x] in 'rptnLT': zone[y][x] = i
        return f
    for e, rg in areas:
        if tag(e).get('highway') and tag(e).get('name') and tag(e)['name'] != 'Plaça de la Vila':
            fill_rings(rg, zone_fill(tag(e)['name']))
    for w in ways.values():
        t = tag(w)
        if t.get('highway') in WIDTH and t.get('name') and t.get('area') != 'yes':
            fill_line(w['nodes'], WIDTH[t['highway']] + 2, zone_fill(t['name']))
    for y in range(N):
        for x in range(N):
            if grid[y][x] in 'pae' and zone[y][x] == -1: zone[y][x] = 0

    xs = [x for y in range(N) for x in range(N) if snapshot[y][x] in '.e']
    ys = [y for y in range(N) for x in range(N) if snapshot[y][x] in '.e']
    anchors = {'monument': [mx, my], 'town': [tx, ty], 'lib': list(map(int, g(nodes[lib['nodes'][0]])))}
    for k, (nm, _) in labels.items():
        if 'Carpeta' in nm: anchors['carpeta'] = list(map(int, k.split(',')))
        if 'Can Sol' in nm: anchors['celler'] = list(map(int, k.split(',')))
    return {
        'N': N, 'S': S, 'plaza': [min(xs), min(ys), max(xs), max(ys)], 'rows': [''.join(r) for r in grid], 'labels': labels, 'anchors': anchors,
        'names': names, 'zones': [''.join(chr(48 + v) if v >= 0 else ' ' for v in r) for r in zone],
        'attribution': '© OpenStreetMap contributors (ODbL)',
    }


def test():
    sq = [[(0, 0), (4, 0), (4, 4), (0, 4)], [(1, 1), (3, 1), (3, 3), (1, 3)]]
    assert inside((.5, .5), sq) and not inside((2, 2), sq), 'forat del multipolígon'
    assert seg_dist((1, 1), (0, 0), (2, 0)) == 1
    rel = {'members': [{'type': 'way', 'ref': 1}, {'type': 'way', 'ref': 2}]}
    assert rings_of(rel, {1: {'nodes': [1, 2, 3]}, 2: {'nodes': [1, 4, 3]}}) == [[1, 4, 3, 2, 1]], 'unió d\'anells'
    m = build(json.load(open(OSM))['elements'])
    rows = m['rows']; c = m['N'] // 2
    assert rows[c - 1][c - 1] == 'm', 'monument al centre'
    assert 'R' in ''.join(rows[c:]), 'Ajuntament al sud'
    assert any(ch in 'Kl' for ch in ''.join(rows[:c])), 'Biblioteca al nord'
    print('ok')


if __name__ == '__main__':
    if '--test' in sys.argv: test(); sys.exit()
    if '--fetch' in sys.argv or not os.path.exists(OSM): fetch()
    m = build(json.load(open(OSM))['elements'])
    with open(OUT, 'w') as f:
        f.write('// Generat per tools/osm2map.py a partir d\'OpenStreetMap. No editar a mà.\n')
        f.write('const OSM_MAP = ' + json.dumps(m, ensure_ascii=False) + ';\n')
    print(f"map.js: {m['N']}x{m['N']} tiles, {len(m['labels'])} rètols, carrers: {', '.join(m['names'])}")
    print('\n'.join(m['rows']))
