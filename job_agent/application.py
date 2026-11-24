"""Inspect an application and rehearse filling it on an isolated local form."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

BLOCK = ('iframe[src*="captcha" i], [class*="captcha" i], [id*="captcha" i], '
         'input[type="password"], input[autocomplete="one-time-code"]')
BLOCK_TEXT = ('verify you are human', 'two-factor authentication', 'multi-factor authentication',
              'access denied', 'security check', 'enable javascript and cookies to continue')


def inspect_form(page):
    blocked = page.locator(BLOCK).count() > 0
    if not blocked:
        body = page.locator('body').inner_text().casefold()
        blocked = any(marker in body for marker in BLOCK_TEXT)
    if blocked:
        return {'blocked': True, 'fields': []}
    fields = page.locator('form input:not([type=hidden]), form select, form textarea').evaluate_all(
        """nodes => nodes.map(n => ({
            id:n.id, name:n.name, type:n.type, required:n.required, disabled:n.disabled,
            label:[...(n.labels || [])].map(l => l.innerText).join(' ') || n.getAttribute('aria-label') || '',
            options:n.tagName === 'SELECT' ? [...n.options].map(o => ({label:o.label,value:o.value})) : []
        }))""")
    return {'blocked': False, 'fields': fields}


def fill_preview(page, field_values, uploads):
    state = inspect_form(page)
    if state['blocked']:
        raise ValueError('Site requires manual access or verification')
    fields = {field['id']: field for field in state['fields'] if field['id']}
    if set(field_values) & set(uploads):
        raise ValueError('A field cannot receive both a value and an upload')
    changed = []
    for field_id, value in {**field_values, **uploads}.items():
        field = fields.get(field_id)
        if not field or field['disabled'] or field['type'] in ('submit', 'reset', 'button', 'image'):
            raise ValueError(f'Field unavailable: {field_id}')
        locator = page.locator('[id=' + json.dumps(field_id) + ']')
        if locator.count() != 1 or not locator.is_visible():
            raise ValueError(f'Field must be uniquely visible: {field_id}')
        if field_id in uploads:
            path = Path(value).resolve(strict=True)
            if field['type'] != 'file' or path.suffix.lower() not in ('.pdf', '.docx'):
                raise ValueError('Resume upload requires a PDF or DOCX file input')
            locator.set_input_files(path)
        elif field['type'] in ('select-one', 'select-multiple'):
            locator.select_option(value)
        elif field['type'] in ('checkbox', 'radio'):
            if not isinstance(value, bool):
                raise ValueError(f'Expected boolean for {field_id}')
            locator.set_checked(value)
        elif field['type'] == 'file':
            raise ValueError('Use the explicit uploads mapping for attachments')
        else:
            locator.fill(value)
        changed.append(field_id)
    return changed


def run(url, *, fixture=None, values=None, uploads=None, executable=None):
    if fixture is None:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('An HTTPS job page is required')
        if values or uploads:
            raise ValueError('Live filling and uploading require an authorized interactive session')
    with sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path=executable)
        context = browser.new_context(service_workers='block', accept_downloads=False)
        try:
            context.route_web_socket('**/*', lambda socket: socket.close())
            page = context.new_page()
            if fixture is not None:
                # A trusted local test fixture only. Blocking all requests keeps file data local.
                context.route('**/*', lambda request: request.abort())
                page.set_content(Path(fixture).read_text())
            else:
                def allow_read(route):
                    request = route.request
                    parsed_request = urlsplit(request.url)
                    if (request.method != 'GET' or parsed_request.scheme != 'https'
                            or parsed_request.hostname != parsed.hostname
                            or (parsed_request.port or 443) != (parsed.port or 443)):
                        route.abort()
                    else:
                        route.continue_()
                context.route('**/*', allow_read)
                page.goto(url, wait_until='domcontentloaded', timeout=30000)
            state = inspect_form(page)
            changed = fill_preview(page, values or {}, uploads or {}) if values or uploads else []
            return {**state, 'filled_field_ids': changed, 'mode': 'DRY_RUN',
                    'submission_state': 'awaiting_user_confirmation'}
        finally:
            context.close()
            browser.close()


def interactive_application(url, values, uploads, executable=None):
    """Opt-in headed session for a user present at the terminal and browser."""
    import sys
    from concurrent.futures import ThreadPoolExecutor

    def ask(page, prompt):
        with ThreadPoolExecutor(max_workers=1) as executor:
            answer = executor.submit(input, prompt)
            while not answer.done():
                page.wait_for_timeout(150)
            return answer.result()

    target = urlsplit(url)
    if target.scheme != 'https' or not target.hostname or target.username or target.password:
        raise ValueError('An HTTPS job page is required')
    if not sys.stdin.isatty():
        raise ValueError('An interactive terminal is required')
    origin = (target.scheme, target.hostname, target.port or 443)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=False, executable_path=executable)
        context = browser.new_context(service_workers='block', accept_downloads=False)
        released = False
        preparing = False

        def protect(route):
            request = route.request
            parts = urlsplit(request.url)
            same_origin = (parts.scheme, parts.hostname, parts.port or 443) == origin
            if not same_origin or (not released and (preparing or request.method != 'GET')):
                route.abort()
            else:
                route.continue_()

        try:
            context.route('**/*', protect)
            context.route_web_socket('**/*', lambda socket: socket.close())
            page = context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=30000)
            state = inspect_form(page)
            if state['blocked'] or not state['fields']:
                raise ValueError('No accessible application form; use the official site manually')
            print(json.dumps(state, ensure_ascii=False, indent=2))
            print('Review the site and field IDs. Writes are blocked while fields are prepared.')
            if ask(page, 'Type PREVIEW to put the selected information into the browser: ') != 'PREVIEW':
                return {'submission_state': 'cancelled'}
            preparing = True
            changed = fill_preview(page, values, uploads)
            print('Prepared field IDs:', ', '.join(changed))
            if inspect_form(page)['blocked']:
                raise ValueError('The site now requires manual access or verification')
            if ask(page, f'Type CONFIRM {target.hostname} to allow you to submit in the browser: ') != f'CONFIRM {target.hostname}':
                return {'submission_state': 'cancelled'}
            released = True
            ask(page, 'Submit manually if the fields are correct, then press Enter to close this session: ')
            return {'submission_state': 'confirmation_required_from_receipt', 'filled_field_ids': changed}
        finally:
            context.close()
            browser.close()


def notion_suggestion(receipt, job):
    if receipt.get('confirmed_by_user') is not True or not receipt.get('evidence_url') or not receipt.get('date'):
        raise ValueError('A user-confirmed submission receipt is required')
    from datetime import date
    day = date.fromisoformat(receipt['date']).isoformat()
    if not (job.get('job_id') or job.get('url')):
        raise ValueError('An official job ID or URL is required')
    return {'mode': 'DRY_RUN', 'job_id': job.get('job_id'), 'jd_url': job.get('url'),
            'suggested_fields': {'狀態': '已投遞', '投遞日期': day},
            'evidence_url': receipt['evidence_url']}


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--url')
    source.add_argument('--fixture')
    parser.add_argument('--values', type=Path)
    parser.add_argument('--chromium')
    parser.add_argument('--interactive', action='store_true', help='Requires separate live approval')
    args = parser.parse_args()
    form = json.loads(args.values.read_text()) if args.values else {}
    if args.interactive:
        if not args.url or not args.values:
            parser.error('--interactive requires --url and --values')
        result = interactive_application(args.url, form.get('values', {}), form.get('uploads', {}),
                                         args.chromium)
    else:
        result = run(args.url, fixture=args.fixture, values=form.get('values'),
                     uploads=form.get('uploads'), executable=args.chromium)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
