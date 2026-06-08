import os
import urllib.request
import json

SUPABASE_URL = os.environ['SUPABASE_URL']
KEY = os.environ['SUPABASE_ANON_KEY']
HEADERS = {'apikey': KEY, 'Authorization': 'Bearer ' + KEY}
PAGE = 1000


def fetch_page(offset):
    url = SUPABASE_URL + '/rest/v1/ticker_names?select=ticker,corp,ko&limit=' + str(PAGE) + '&offset=' + str(offset)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


all_rows = []
offset = 0
while True:
    rows = fetch_page(offset)
    if not rows:
        break
    all_rows.extend(rows)
    print('  수집 중... ' + str(len(all_rows)) + '개')
    if len(rows) < PAGE:
        break
    offset += PAGE

print('총 ' + str(len(all_rows)) + '개 수집 완료')

lines = ['TRUNCATE ticker_names;']
lines.append('INSERT INTO ticker_names (ticker, corp, ko) VALUES')

vals = []
for r in all_rows:
    t = r['ticker'].replace("'", "''")
    c = r['corp'].replace("'", "''")
    k = (r.get('ko') or '').replace("'", "''")
    vals.append("('" + t + "','" + c + "','" + k + "')")

lines.append(',\n'.join(vals))
lines.append('ON CONFLICT (ticker) DO UPDATE SET corp=EXCLUDED.corp, ko=EXCLUDED.ko;')

with open('/tmp/tickers.sql', 'w') as f:
    f.write('\n'.join(lines))

print('SQL 파일 생성 완료: /tmp/tickers.sql')
