#!/usr/bin/env python3
"""Recupere le catalogue WooCommerce (API Store publique) et les photos produits,
puis ecrit data/products.json pour les pages produit de la maquette."""
import json, os, re, subprocess, sys, html, urllib.request, urllib.error

SITE = sys.argv[1].rstrip('/')          # ex: https://gossipbrand.fr
MAX_IMG = int(os.environ.get('MAX_IMG', '6'))
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh) Chrome/124', 'Accept': 'application/json'}
UPLOADS = SITE + '/wp-content/uploads/'
SKIP_CATS = {'femme', 'uncategorized', 'non classé', 'clothing', 'chaussures', 'outlet'}
BRANDS = ['Dior', 'Moncler', 'Stone Island', 'Casablanca', 'Off-White', 'OFF WHITE', 'Gucci', 'Prada', 'Burberry',
          'Yves Saint Laurent', 'Saint Laurent', 'Jacquemus', 'CP company', 'C.P. Company', 'Salomon', 'SALOMON',
          'ASICS', 'Saucony', 'SAUCONY', 'Nike', 'Adidas', 'Timberland', 'Balenciaga', 'Louis Vuitton', 'Amiri',
          'Palm Angels', 'Canada Goose', 'Valentino', 'Versace', 'Fendi', 'Givenchy', 'Celine', 'Loewe', 'New Balance']


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode('utf-8'))


def text(h):
    h = re.sub(r'<br\s*/?>', '\n', h or '')
    h = re.sub(r'</p>\s*<p[^>]*>', '\n', h)
    return html.unescape(re.sub(r'<[^>]+>', '', h)).strip()


def money(prices, key):
    v = prices.get(key)
    if v in (None, ''):
        return None
    return round(int(v) / 10 ** int(prices.get('currency_minor_unit', 2)), 2)


def local(src):
    src = src.split('?')[0]
    if not src.startswith(UPLOADS):
        return None, None
    rel = src[len(UPLOADS):]
    return src, 'img/' + rel


def fetch_img(src, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = subprocess.run(['curl', '-fsSL', '--retry', '3', '-A', UA['User-Agent'], src, '-o', path])
    if r.returncode != 0:
        if os.path.exists(path):
            os.remove(path)
        return False
    if path.lower().endswith(('.jpg', '.jpeg', '.png')):
        try:
            from PIL import Image
            im = Image.open(path)
            if max(im.size) > 1600:
                im.thumbnail((1600, 1600))
            if path.lower().endswith('.png'):
                im.save(path, optimize=True)
            else:
                im.convert('RGB').save(path, quality=82, optimize=True, progressive=True)
        except Exception as e:
            print('resize ignore', path, e)
    return True


# photos de la page d'accueil (images.txt)
if os.path.exists('images.txt'):
    n = 0
    for line in open('images.txt'):
        parts = line.split()
        if len(parts) == 2 and fetch_img(parts[0], parts[1]):
            n += 1
    print('Photos accueil:', n)


def brand_of(name):
    low = name.lower()
    for b in BRANDS:
        if low.startswith(b.lower()) or (' ' + b.lower() + ' ') in (' ' + low + ' '):
            nice = {'OFF WHITE': 'Off-White', 'SALOMON': 'Salomon', 'SAUCONY': 'Saucony', 'CP company': 'C.P. Company',
                    'Yves Saint Laurent': 'Saint Laurent'}.get(b, b)
            return nice, b
    return '', ''


products, page = [], 1
while True:
    batch = get(f'{SITE}/wp-json/wc/store/v1/products?per_page=100&page={page}')
    if not batch:
        break
    products += batch
    if len(batch) < 100:
        break
    page += 1
print('Produits:', len(products))

out, ok_img, ko_img = [], 0, 0
for p in products:
    raw = html.unescape(p['name'])
    pre = ''
    m = re.search(r'\(?\s*pr[ée]\s*-?\s*commande\s*([^)]*)\)?', raw, re.I)
    if m:
        pre = re.sub(r'\s+', ' ', m.group(1)).strip(' -:') or 'Précommande'
        raw = (raw[:m.start()] + raw[m.end():]).strip(' -(')
    raw = re.sub(r'\s+', ' ', raw).strip()
    name = raw[:1].upper() + raw[1:]
    brand, rawb = brand_of(name)
    model = name
    if rawb and name.lower().startswith(rawb.lower()):
        model = name[len(rawb):].strip(' -') or name
        model = model[:1].upper() + model[1:]
    imgs = []
    for im in p.get('images', [])[:MAX_IMG]:
        src, path = local(im['src'])
        if not src:
            continue
        if fetch_img(src, path):
            imgs.append(path); ok_img += 1
        else:
            imgs.append(src); ko_img += 1
    sizes, colors = [], []
    for a in p.get('attributes', []):
        terms = [html.unescape(t['name']) for t in a.get('terms', [])]
        terms = list(dict.fromkeys(terms))
        n = a.get('name', '').lower()
        if any(k in n for k in ('taille', 'pointure', 'size')):
            sizes = terms
        elif any(k in n for k in ('couleur', 'color', 'coloris')):
            colors = terms
    # disponibilite par taille (variations)
    avail = {}
    for v in p.get('variations', [])[:20]:
        try:
            vd = get(f"{SITE}/wp-json/wc/store/v1/products/{v['id']}")
        except Exception:
            continue
        for va in v.get('attributes', []):
            val = html.unescape(str(va.get('value', '')))
            for s in sizes:
                if s.lower().replace(' ', '-') == val.lower().replace(' ', '-') or s.lower() == val.lower():
                    avail[s] = bool(vd.get('is_in_stock'))
    prices = p.get('prices', {})
    cats = [html.unescape(c['name']) for c in p.get('categories', []) if c['name'].lower() not in SKIP_CATS]
    out.append({
        'slug': p['slug'], 'name': name, 'brand': brand, 'model': model, 'pre': pre,
        'price': money(prices, 'price'), 'regular': money(prices, 'regular_price'),
        'on_sale': bool(p.get('on_sale')), 'in_stock': bool(p.get('is_in_stock')),
        'short': text(p.get('short_description')), 'desc': text(p.get('description')),
        'cats': cats or [html.unescape(c['name']) for c in p.get('categories', [])][:1],
        'sizes': sizes, 'avail': avail, 'colors': colors, 'images': imgs,
        'src0': local(p['images'][0]['src'])[0] if p.get('images') else '',
        'sku': p.get('sku', ''),
    })

os.makedirs('data', exist_ok=True)
with open('data/products.json', 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
print(f'products.json: {len(out)} fiches · photos OK {ok_img} · echecs {ko_img}')
