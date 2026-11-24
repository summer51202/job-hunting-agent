"""Read-only adapters for connector snapshots and official Notion/Gmail APIs.
No write methods, no browser automation, and no token persistence.
"""
from __future__ import annotations
import base64, json, os, urllib.parse, urllib.request
from datetime import date, datetime, time
from zoneinfo import ZoneInfo
from uuid import UUID
from typing import Any
from .core import clean


def normalize_notion_rows(payload: Any) -> list[dict]:
    if isinstance(payload, str): payload = json.loads(payload)
    if isinstance(payload, dict) and isinstance(payload.get('text'), str): payload = json.loads(payload['text'])
    if isinstance(payload, dict) and payload.get('has_more'):
        raise ValueError('Notion snapshot is incomplete')
    rows = payload['results'] if isinstance(payload, dict) else payload
    result = []
    for row in rows:
        if 'company' in row or 'job_id' in row:
            result.append(row)
            continue
        # Supports connector rows and official Notion API page objects.
        if 'properties' in row:
            props = row['properties']
            def value(key):
                p = props.get(key, {})
                t = p.get('type', '')
                if t in ('title', 'rich_text'):
                    return ''.join(v.get('plain_text', v.get('text', {}).get('content', '')) for v in p.get(t, []))
                if t in ('status', 'select'): return (p.get(t) or {}).get('name', '')
                if t == 'url': return p.get('url') or ''
                if t == 'date': return (p.get('date') or {}).get('start', '')
                return ''
            url = row.get('url', '')
            date = value('結案日期')
            applied = value('投遞日期')
        else:
            value = lambda k: row.get(k, '')
            url = row.get('url', '')
            date = row.get('date:結案日期:start', '')
            applied = row.get('date:投遞日期:start', '')
        result.append({'company':clean(value('公司')), 'title':clean(value('職位')),
                       'job_id':clean(value('Job ID')), 'status':clean(value('狀態')),
                       'stage':clean(value('目前階段')), 'closed_date':date or '',
                       'applied_date': applied or '', 'url':url, 'jd_url':value('JD 連結') or '',
                       'notes':clean(value('備註'))})
    return result


def normalize_gmail_summaries(payload: Any) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get('result', payload)
        if payload.get('next_page_token'):
            raise ValueError('Gmail snapshot is incomplete')
        payload = payload['emails']
    return [{**e, 'date': e.get('date') or e.get('email_ts', ''),
             'from': e.get('from') or e.get('from_', ''),
             'body': e.get('body') or e.get('snippet', ''),
             'url': e.get('url') or e.get('display_url', ''),
             'body_complete': e.get('body_complete') is True} for e in payload]


def gmail_queries(since):
    start = datetime.combine(date.fromisoformat(since), time(), ZoneInfo('Asia/Taipei'))
    prefix = f'after:{int(start.timestamp()) - 1} -in:trash -in:spam '
    senders = ('mail.amazon.jobs', 'scheduling.amazon.jobs', 'email.careers.microsoft.com',
               'myworkday.com', 'talent.icims.com', 'trinethire.com', 'invites.starred.com',
               'waymo.com', 'cerence.com', 'xwf.google.com', 'greenhouse.io', 'lever.co')
    keywords = ('application', 'interview', 'assessment', 'recruiter', 'candidacy', '面試', '應徵')
    return [prefix + 'label:Jobs',
            prefix + '{' + ' '.join('from:' + sender for sender in senders) + '}',
            prefix + '{' + ' '.join('subject:' + word for word in keywords) + '}']


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def fetch_notion_readonly(database_id: str, token: str | None = None, *, data_source=False) -> list[dict]:
    """Uses official Notion API; integration must have read access to database."""
    token = token or os.getenv('NOTION_TOKEN')
    if not token: raise ValueError('Missing NOTION_TOKEN (read-only integration recommended)')
    database_id = str(UUID(database_id))
    resource = 'data_sources' if data_source else 'databases'
    version = '2025-09-03' if data_source else '2022-06-28'
    headers = {'Authorization': f'Bearer {token}', 'Notion-Version': version}
    # API database query uses POST, which is semantically read-only; explicit allowlist.
    items, cursor = [], None
    while True:
        data = {'page_size':100}
        if cursor: data['start_cursor'] = cursor
        req = urllib.request.Request(f'https://api.notion.com/v1/{resource}/{database_id}/query',
            data=json.dumps(data).encode(), headers={**headers,'Content-Type':'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response: page = json.load(response)
        items.extend(page['results'])
        if not page.get('has_more'): break
        cursor = page.get('next_cursor')
        if not cursor: raise RuntimeError('Notion pagination incomplete')
    return normalize_notion_rows(items)


def fetch_gmail_readonly(access_token: str, queries: list[str], max_pages: int = 20) -> list[dict]:
    """Requires a Google OAuth token with gmail.readonly scope; never stores it."""
    headers = {'Authorization': 'Bearer '+access_token}
    seen, result = set(), []
    for query in queries:
        token = None
        for _ in range(max_pages):
            params = {'q':query, 'maxResults':100}
            if token: params['pageToken'] = token
            url = 'https://gmail.googleapis.com/gmail/v1/users/me/messages?'+urllib.parse.urlencode(params)
            page = _get_json(url, headers)
            for item in page.get('messages', []):
                mid = item['id']
                if mid in seen: continue
                seen.add(mid)
                msg = _get_json('https://gmail.googleapis.com/gmail/v1/users/me/messages/'+mid+'?format=full', headers)
                hs = {h['name'].lower():h['value'] for h in msg.get('payload',{}).get('headers',[])}
                def parts(p):
                    out = []
                    if p.get('mimeType') in ('text/plain', 'text/html') and not p.get('filename') and p.get('body',{}).get('data'):
                        raw=p['body']['data']; out.append((p['mimeType'], base64.urlsafe_b64decode(raw+'='*(-len(raw)%4)).decode('utf-8','replace')))
                    for child in p.get('parts',[]): out.extend(parts(child))
                    return out
                bodies = parts(msg.get('payload', {}))
                mime, body = next((p for p in bodies if p[0] == 'text/plain'),
                                  bodies[0] if bodies else ('', ''))
                result.append({'id':mid,'date':datetime.fromtimestamp(int(msg['internalDate']) / 1000, ZoneInfo('Asia/Taipei')).isoformat() if msg.get('internalDate') else hs.get('date',''),'from':hs.get('from',''),'subject':hs.get('subject',''),
                               'body':body or msg.get('snippet',''), 'body_complete':bool(body), 'body_html': mime == 'text/html',
                               'url':'https://mail.google.com/mail/u/0/#all/'+mid})
            token = page.get('nextPageToken')
            if not token: break
        else: raise RuntimeError('Gmail search exceeded max_pages; narrow query')
    return result


class NotionReviewGateway:
    """Opt-in official API transport for an authorized, reviewed Phase 1 write."""

    def __init__(self, token, data_source_id):
        if not token:
            raise ValueError('A separately authorized write credential is required')
        self.token = token
        self.data_source_id = str(UUID(data_source_id))

    def _page(self, record_url, fields=None):
        page_id = str(UUID(urllib.parse.urlsplit(record_url).path.rsplit('/', 1)[-1]))
        data = json.dumps({'properties': fields}).encode() if fields is not None else None
        request = urllib.request.Request(
            'https://api.notion.com/v1/pages/' + page_id, data=data,
            headers={'Authorization': f'Bearer {self.token}', 'Notion-Version': '2025-09-03',
                     'Content-Type': 'application/json'},
            method='PATCH' if data is not None else 'GET')
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def read(self, record_url):
        page = self._page(record_url)
        if page.get('parent', {}).get('data_source_id') != self.data_source_id:
            raise ValueError('Proposed record is outside the authorized Notion data source')
        row = normalize_notion_rows([page])[0]
        return {key: row[key] for key in ('status', 'closed_date')}

    def update(self, record_url, fields):
        self._page(record_url, {'狀態': {'status': {'name': fields['status']}},
                                '結案日期': {'date': {'start': date.fromisoformat(fields['closed_date']).isoformat()}}})
