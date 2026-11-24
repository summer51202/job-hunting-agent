"""Read-only, TLS-verified probes for supported recruiting destinations."""
import argparse
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


@dataclass(frozen=True)
class Platform:
    company: str
    hosts: tuple[str, ...]
    entry: str
    markers: tuple[str, ...]
    requisition: str = ''


PLATFORMS = (
    Platform('AMD', ('careers.amd.com',), 'https://careers.amd.com/careers-home/jobs/80713',
             ('icims', 'phenom'), r'/jobs/(\d+)'),
    Platform('NVIDIA', ('nvidia.wd5.myworkdayjobs.com', 'www.nvidia.com'),
             'https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite',
             ('myworkdayjobs', 'workday'), r'\b(JR\d+)\b'),
    Platform('Qualcomm', ('careers.qualcomm.com',), 'https://careers.qualcomm.com/careers',
             ('eightfold', 'qualcomm'), r'[?&]pid=(\d+)'),
    Platform('Google', ('www.google.com',),
             'https://www.google.com/about/careers/applications/jobs/results/',
             ('google careers', 'careers/applications'), r'/results/(\d+)'),
    Platform('Amazon', ('www.amazon.jobs', 'amazon.jobs'), 'https://www.amazon.jobs/en/',
             ('amazon jobs', 'amazon.jobs'), r'/jobs/(\d+)'),
    Platform('Garmin', ('careers.garmin.com',), 'https://careers.garmin.com/',
             ('garmin', 'icims'), r'/jobs/(\d+)'),
)


class PageFacts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title = ''
        self.forms = 0
        self.upload_fields = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.in_title = True
        if tag == 'form':
            self.forms += 1
        if tag == 'input' and dict(attrs).get('type') == 'file':
            self.upload_fields += 1

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def valid_url(url, hosts):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname in hosts and not parsed.username
            and not parsed.password and parsed.port in (None, 443))


def probe(platform, url=None):
    url = url or platform.entry
    if not valid_url(url, platform.hosts):
        raise ValueError('URL is outside the platform allowlist')

    class Redirect(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, destination):
            if not valid_url(destination, platform.hosts):
                raise HTTPError(request.full_url, code, 'External redirect requires manual access', headers, fp)
            return super().redirect_request(request, fp, code, message, headers, destination)

    match = re.search(platform.requisition, url) if platform.requisition else None
    output = {'platform': platform.company, 'url': url, 'requisition': match[1] if match else None,
              'mode': 'DRY_RUN'}
    try:
        with build_opener(Redirect()).open(Request(url, headers={'User-Agent': 'JobAgentReadOnly/1.0'}),
                                          timeout=15) as response:
            html = response.read(2_000_000).decode(response.headers.get_content_charset() or 'utf-8', 'replace')
            facts = PageFacts()
            facts.feed(html)
            return {**output, 'http': response.status, 'tls_verified': True, 'title': facts.title.strip(),
                    'markers': [marker for marker in platform.markers if marker in html.casefold()],
                    'static_forms': facts.forms, 'static_upload_fields': facts.upload_fields,
                    'scope': 'public_http_only'}
    except HTTPError as error:
        return {**output, 'http': error.code, 'tls_verified': True,
                'scope': 'blocked_or_redirect', 'detail': str(error.reason)}
    except (URLError, TimeoutError) as error:
        return {**output, 'http': None, 'tls_verified': None,
                'scope': 'connection_error', 'detail': str(getattr(error, 'reason', error))}


def main():
    from concurrent.futures import ThreadPoolExecutor
    parser = argparse.ArgumentParser()
    parser.add_argument('--company', choices=[platform.company for platform in PLATFORMS])
    parser.add_argument('--url')
    args = parser.parse_args()
    if args.url and not args.company:
        parser.error('--url requires --company')
    selected = [platform for platform in PLATFORMS if not args.company or platform.company == args.company]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda platform: probe(platform, args.url), selected))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
