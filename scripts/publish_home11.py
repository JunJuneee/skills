import base64
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CREDENTIALS_DIR = Path(os.environ.get('LILIS_BLOGGER_CREDENTIALS_DIR', '/Users/jun/.config/lilis-blog'))
CLIENT_SECRET_PATH = Path(os.environ.get('GOOGLE_BLOGGER_CLIENT_SECRET', CREDENTIALS_DIR / 'google-client-secret.json'))
TOKEN_PATH = Path(os.environ.get('GOOGLE_BLOGGER_TOKEN_PATH', CREDENTIALS_DIR / 'blogger-tokens.json'))
BLOG_ID_CACHE_PATH = Path(os.environ.get('GOOGLE_BLOGGER_BLOG_ID_CACHE_PATH', CREDENTIALS_DIR / 'blog-id-cache.json'))
SOURCE = Path('/Users/jun/Documents/블로그 포스팅/8월1일_홈쇼핑_시간대별_게시글/8월1일_11시_홈쇼핑_편성표.md')
ASSETS = Path('/private/tmp/home11')
TITLE = '8월 1일 11시 홈쇼핑 편성표｜대표상품·함께방송 상품 링크'
LABELS = ['홈쇼핑', '홈쇼핑편성표', '11시홈쇼핑', '오늘의홈쇼핑', '홈쇼핑방송', '홈쇼핑상품', '홈쇼핑할인']

def image(name, alt):
    payload = base64.b64encode((ASSETS / name).read_bytes()).decode()
    return f'<p class="post-image"><img src="data:image/jpeg;base64,{payload}" alt="{alt}" loading="lazy"></p>'

def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" rel="nofollow noopener">\1</a>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    return text

def table(rows):
    parsed=[]
    for row in rows:
        cells=[c.strip() for c in row.strip().strip('|').split('|')]
        parsed.append(cells)
    headers=parsed[0]
    body=[r for r in parsed[2:] if len(r)==len(headers)]
    head=''.join(f'<th>{inline(c)}</th>' for c in headers)
    rows_html=''.join('<tr>'+''.join(f'<td>{inline(c)}</td>' for c in row)+'</tr>' for row in body)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{rows_html}</tbody></table></div>'

def markdown_to_html(markdown):
    lines=markdown.splitlines()
    out=[]; i=0
    while i < len(lines):
        line=lines[i]
        if not line.strip():
            i+=1; continue
        if line.startswith('> '):
            out.append(f'<blockquote>{inline(line[2:])}</blockquote>'); i+=1; continue
        if line.startswith('### '):
            ident=re.sub(r'[^a-z0-9가-힣]+','-',line[4:].lower()).strip('-')
            out.append(f'<h3 id="{ident}">{inline(line[4:])}</h3>'); i+=1; continue
        if line.startswith('## '):
            ident=re.sub(r'[^a-z0-9가-힣]+','-',line[3:].lower()).strip('-')
            out.append(f'<h2 id="{ident}">{inline(line[3:])}</h2>'); i+=1; continue
        if line.startswith('# '):
            i+=1; continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                rows.append(lines[i]); i+=1
            out.append(table(rows)); continue
        if re.match(r'^[-*] ',line) or line.startswith('□ '):
            items=[]
            while i<len(lines) and (re.match(r'^[-*] ',lines[i]) or lines[i].startswith('□ ')):
                items.append(re.sub(r'^[-*] |^□ ','',lines[i])); i+=1
            out.append('<ul>'+''.join(f'<li>{inline(x)}</li>' for x in items)+'</ul>'); continue
        paragraph=[line]
        i+=1
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','> ','|','- ','* ','□ ')):
            paragraph.append(lines[i]); i+=1
        out.append(f'<p>{inline(" ".join(paragraph))}</p>')
    return '\n'.join(out)

source=SOURCE.read_text()
intro_marker='## 11시 홈쇼핑 대표상품 편성표\n\n'
cards='\n\n'.join([
    image('card_02.jpg','8월 1일 11시 홈쇼핑 대표상품 카드 1'),
    image('card_03.jpg','8월 1일 11시 홈쇼핑 대표상품 카드 2'),
    image('card_04.jpg','8월 1일 11시 홈쇼핑 대표상품 카드 3'),
    image('card_05.jpg','8월 1일 11시 홈쇼핑 대표상품 카드 4'),
])
source=source.replace(intro_marker, intro_marker+'대표상품은 해당 방송에서 중심으로 소개되는 구성입니다.\n\n@@REPRESENTATIVE_CARDS@@\n\n', 1)
source=source.replace('## 함께 보면 좋은 글\n\n- 오늘의 홈쇼핑 편성표 채널별 확인 방법\n- 홈쇼핑 카드 할인과 무이자 할부 확인 방법\n- 홈쇼핑 건강식품 구매 전 확인사항\n- 홈쇼핑 여행 상품 예약 전 체크리스트', '''## 함께 보면 좋은 글

- [8월 1일 10시 홈쇼핑 편성표｜대표상품·함께방송 상품 링크](https://betterpickguide.blogspot.com/2026/08/8-1-10.html)
- [8월 1일 9시 홈쇼핑 편성표｜대표상품·함께방송 상품 링크](https://betterpickguide.blogspot.com/2026/08/8-1-9.html)
- [8월 1일 오전 8시 홈쇼핑 편성표｜대표상품·함께방송 상품 링크](https://betterpickguide.blogspot.com/2026/08/8-1-8.html)''')
content = '''<style>
.bp-post{max-width:850px;margin:auto;font-size:16px;line-height:1.8;color:#222}.bp-post h2{margin:38px 0 14px;font-size:25px;line-height:1.4}.bp-post h3{margin:28px 0 10px;font-size:20px}.bp-post p{margin:15px 0}.bp-post blockquote{margin:18px 0;padding:13px 16px;border-left:4px solid #ef6c5b;background:#fff6f2}.bp-post .post-image{text-align:center;margin:24px 0}.bp-post img{max-width:100%;height:auto;border-radius:4px}.bp-post .table-wrap{overflow-x:auto;margin:18px 0}.bp-post table{width:100%;border-collapse:collapse;font-size:14px}.bp-post th,.bp-post td{padding:9px;border:1px solid #ddd;text-align:left;vertical-align:top;white-space:normal}.bp-post th{background:#fff1eb}.bp-post a{color:#a64433;text-decoration:underline}.bp-post ul{padding-left:22px}.bp-post code{background:#f2f2f2;padding:1px 4px;border-radius:3px}
</style><article class="bp-post">'''
content += image('card_01.jpg','8월 1일 11시 홈쇼핑 편성표 표지')
content += markdown_to_html(source)
content = content.replace('<p>@@REPRESENTATIVE_CARDS@@</p>', cards)
content += '<h2>홈쇼핑 편성표 더 보기</h2>'
content += image('cta.jpg','8월 1일 홈쇼핑 편성표 더 보기')
content += '</article>'

expected_alts=re.findall(r'<img[^>]+alt="([^"]+)"',content)
secret=json.loads(CLIENT_SECRET_PATH.read_text())
oauth=secret.get('web') or secret.get('installed')
tokens=json.loads(TOKEN_PATH.read_text())
cache=json.loads(BLOG_ID_CACHE_PATH.read_text())
refresh=urlencode({'client_id':oauth['client_id'],'client_secret':oauth['client_secret'],'refresh_token':tokens['refresh_token'],'grant_type':'refresh_token'}).encode()
with urlopen(Request('https://oauth2.googleapis.com/token',data=refresh,method='POST'),timeout=60) as response:
    token=json.load(response)['access_token']
payload=json.dumps({'title':TITLE,'content':content,'labels':LABELS},ensure_ascii=False).encode()
headers={'Authorization':f'Bearer {token}','Content-Type':'application/json; charset=utf-8'}
list_endpoint=f"https://www.googleapis.com/blogger/v3/blogs/{cache['blogId']}/posts?maxResults=100&fetchBodies=false"
with urlopen(Request(list_endpoint,headers=headers),timeout=60) as response:
    matches=[item for item in json.load(response).get('items',[]) if item.get('title')==TITLE]
if matches:
    latest=max(matches,key=lambda item:item.get('published',''))
    endpoint=f"https://www.googleapis.com/blogger/v3/blogs/{cache['blogId']}/posts/{latest['id']}?fetchBody=true&fetchImages=true"
    method='PUT'
else:
    endpoint=f"https://www.googleapis.com/blogger/v3/blogs/{cache['blogId']}/posts?isDraft=false&fetchBody=true&fetchImages=true"
    method='POST'
request=Request(endpoint,data=payload,method=method,headers=headers)
with urlopen(request,timeout=120) as response:
    result=json.load(response)
stored=result.get('content','')
stored_alts=re.findall(r'<img[^>]+alt="([^"]+)"',stored)
if len(expected_alts)!=len(stored_alts) or set(expected_alts)!=set(stored_alts):
    raise RuntimeError(f'image integrity mismatch: expected={expected_alts}, stored={stored_alts}')
print(json.dumps({'title':result.get('title'),'url':result.get('url'),'images':len(stored_alts),'alts':stored_alts},ensure_ascii=False))
