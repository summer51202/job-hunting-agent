"""Rank weekly opportunities and build local English application documents."""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

WEIGHTS = {'technical': 35, 'career': 25, 'salary': 20, 'location': 15, 'interview': 5}
NEUTRAL = 50


def weekly_jobs(markdown):
    jobs = []
    seen = set()
    pattern = r'<Link url="(https://[^"]+)">(.+?)</Link>\s*\|\s*([^|\n]+)\|\s*([^|\n]+)\|\s*([^|\n]+)\|\s*([^|\n]+)'
    for url, role, location, match, gap, referral in re.findall(pattern, markdown):
        if url in seen or not urlsplit(url).hostname:
            continue
        seen.add(url)
        values = [int(n) for n in re.findall(r'\d+(?=\s*(?:[%–—-]))', match)]
        company, sep, title = role.partition(' — ')
        jobs.append(dict(url=url, company=company if sep else '', title=title if sep else role,
                         location=location.strip(), technical=sum(values) / len(values) if values else None,
                         gap=gap.strip(), referral=referral.strip()))
    if not jobs:
        raise ValueError('No weekly report job rows found')
    return jobs


def rank(jobs, assessments=None):
    assessments = assessments or {}
    results = []
    for job in jobs:
        place = job.get('location', '').casefold()
        if re.search(r'taipei|台北|臺北|taiwan remote|台灣遠端', place):
            location = 100
        elif re.search(r'hsinchu|新竹', place):
            location = 30
        elif re.search(r'(apac|worldwide) remote|new taipei|新北', place):
            location = 85
        else:
            location = None
        inputs = {'technical': job.get('technical'), 'location': location}
        overrides = assessments.get(job['url'], {})
        if overrides.keys() - WEIGHTS.keys():
            raise ValueError('Unknown scoring dimension')
        inputs.update(overrides)
        missing = [key for key in WEIGHTS if inputs.get(key) is None]
        scores = {key: NEUTRAL if key in missing else inputs[key] for key in WEIGHTS}
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100
               for value in scores.values()):
            raise ValueError('Scores must be numbers between 0 and 100')
        results.append({**job, 'score': round(sum(scores[k] * w for k, w in WEIGHTS.items()) / 100, 2),
                        'dimensions': scores, 'missing_evidence': missing})
    return sorted(results, key=lambda job: (-job['score'], job['url']))


def tailored_pages(profile, jd):
    """Select verbatim English source bullets using the JD vocabulary."""
    tokens = set(re.findall(r'[a-z][a-z0-9+#./-]{2,}', jd.casefold()))
    if not tokens:
        raise ValueError('A readable job description is required')
    sections = []
    for section in profile['sections']:
        bullets = section['bullets']
        scored = sorted(enumerate(bullets),
                        key=lambda pair: (-len(tokens & set(re.findall(
                            r'[a-z][a-z0-9+#./-]{2,}', pair[1].casefold()))), pair[0]))
        sections.append((section['heading'], [value for _, value in scored]))
    if not sections or not all(heading and bullets and all(bullets) for heading, bullets in sections):
        raise ValueError('Provide sourced English headings and bullets')
    return sections


def cover_letter(profile, job, selected):
    evidence = [item.rstrip('.') for _, bullets in selected for item in bullets][:3]
    if not evidence:
        raise ValueError('Provide verified experience for the letter')
    role = job['title']
    company = job['company']
    paragraphs = [
        'Dear Hiring Team,',
        f'I am applying for the {role} position at {company}. I would welcome the opportunity to discuss the work described in the job posting and how my background could contribute to the team. I have selected the examples below from my resume because they provide concrete starting points for a conversation about my experience.',
        'Relevant examples from my resume include the following.',
        *[item + '.' for item in evidence],
        'In an interview, I would be glad to explain the context behind these examples, the choices I made, and what I learned from the results. I would also like to hear how your team defines success for this role and which problems the person joining the team would be asked to tackle first. That discussion would help us establish where my experience can contribute immediately and where I would need to build additional context.',
        'I would also value the opportunity to discuss how the team works across engineering groups when an issue spans several components. Understanding how the team reviews changes, tests releases, and communicates tradeoffs would help me connect my examples to the day-to-day requirements of the position.',
        'Thank you for reviewing my application. I would appreciate the opportunity to speak with you about the role, share more detail about the examples above, and learn more about the team’s priorities for the coming year.',
        f'Sincerely,\n{profile["name"]}',
    ]
    count = len(re.findall(r"[A-Za-z]+(?:[’'-][A-Za-z]+)*", ' '.join(paragraphs)))
    if not 250 <= count <= 350:
        raise ValueError(f'Cover letter has {count} words; provide concise sourced bullets of suitable length')
    return paragraphs


def document_pair(out, name, paragraphs, *, template=None, pages=1):
    from docx import Document
    from docx.shared import Inches, Pt
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    from pypdf import PdfReader
    from xml.sax.saxutils import escape

    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as stage:
        work = Path(stage)
        docx_path, pdf_path = work / f'{name}.docx', work / f'{name}.pdf'
        if template:
            doc = Document(template)
            markers = {f'{{{{RESUME_PAGE_{i}}}}}': i - 1 for i in range(1, pages + 1)}
            found = set()
            for paragraph in doc.paragraphs:
                text = paragraph.text.strip()
                if text not in markers:
                    continue
                if text in found:
                    raise ValueError('Duplicate template marker')
                found.add(text)
                for style, line in paragraphs[markers[text]]:
                    paragraph.insert_paragraph_before(line, style=style)
                paragraph._element.getparent().remove(paragraph._element)
            if found != set(markers):
                raise ValueError('Template must contain one standalone RESUME_PAGE marker per page')
        else:
            doc = Document()
            for section in doc.sections:
                section.top_margin = section.bottom_margin = Inches(.65)
            doc.styles['Normal'].font.name = 'Arial'
            doc.styles['Normal'].font.size = Pt(10)
            for i, page in enumerate(paragraphs):
                if i:
                    doc.add_page_break()
                for style, line in page:
                    doc.add_paragraph(line, style=style)
        doc.save(docx_path)
        converter = shutil.which('libreoffice') or shutil.which('soffice')
        if converter:
            subprocess.run([converter, f'-env:UserInstallation={ (work / "lo").as_uri() }',
                            '--headless', '--convert-to', 'pdf', '--outdir', str(work), str(docx_path)],
                           check=True, capture_output=True, timeout=60)
        elif template:
            raise ValueError('LibreOffice is required to preserve template styling in the PDF')
        else:
            styles = getSampleStyleSheet()
            items = []
            for i, page in enumerate(paragraphs):
                if i:
                    items.append(PageBreak())
                for style, line in page:
                    key = {'Title': 'Title', 'Heading 1': 'Heading2'}.get(style, 'BodyText')
                    value = escape(line).replace('\n', '<br/>')
                    if style == 'List Bullet':
                        value = '• ' + value
                    items.extend([Paragraph(value, styles[key]), Spacer(1, 4)])
            SimpleDocTemplate(str(pdf_path), topMargin=46, bottomMargin=46).build(items)
        if len(PdfReader(pdf_path).pages) != pages:
            raise ValueError(f'{name} must render to {pages} pages')
        for file in (docx_path, pdf_path):
            file.chmod(0o600)
            file.replace(out / file.name)


def application_docs(profile, job, jd, out, template=None):
    selected = tailored_pages(profile, jd)
    letter = cover_letter(profile, job, selected)
    lines = []
    for heading, bullets in selected:
        lines.append(('Heading 1', heading))
        lines.extend(('List Bullet', bullet) for bullet in bullets)
    split = max(1, (len(lines) + 1) // 2)
    if lines[split - 1][0] == 'Heading 1' and split > 1:
        split -= 1
    first, second = lines[:split], lines[split:]
    if second and second[0][0] == 'List Bullet':
        heading = next(line for style, line in reversed(first) if style == 'Heading 1')
        second = [('Heading 1', heading), *second]
    resume = [[('Title', profile['name']), ('Normal', profile['contact']), *first],
              [('Title', profile['name']), *second]]
    document_pair(out, 'resume', resume, template=template, pages=2)
    document_pair(out, 'cover-letter', [[('Normal', paragraph) for paragraph in letter]])


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    ranking = commands.add_parser('rank')
    ranking.add_argument('weekly', type=Path)
    ranking.add_argument('output', type=Path)
    ranking.add_argument('--assessments', type=Path)
    docs = commands.add_parser('docs')
    for name in ('profile', 'job', 'jd', 'output'):
        docs.add_argument(name, type=Path)
    docs.add_argument('--template', type=Path)
    args = parser.parse_args()
    if args.command == 'rank':
        assessments = json.loads(args.assessments.read_text()) if args.assessments else {}
        result = rank(weekly_jobs(args.weekly.read_text()), assessments)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        application_docs(json.loads(args.profile.read_text()), json.loads(args.job.read_text()),
                         args.jd.read_text(), args.output, args.template)


if __name__ == '__main__':
    main()
