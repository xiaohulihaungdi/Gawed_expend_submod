"""核对12篇文档正文、本地化往返与事件效果保持不变；不启动游戏。"""
from pathlib import Path
import hashlib,json,re,subprocess
from pdx_script import parse
from validate_reform import decode_special,normalized

ROOT=Path(__file__).resolve().parent.parent
def validate():
    mapping=[('威利亚姆改革','gcd_welyam_reform'),('永冻边区事件','gcd_yongdongbianqu'),('凯尔马尔多','gcd_celmaldor')]
    keys={}
    for src,runtime in mapping:
        plain=(ROOT/f'制作源文件/{src}_中文原文.yml').read_text(encoding='utf-8-sig')
        assert decode_special((ROOT/f'localisation/{runtime}_l_english.yml').read_text(encoding='utf-8-sig'))==plain
        rows=re.findall(r'^\s*([\w.]+):\d+\s+(".*")\s*$',plain,re.M)
        assert len(rows)==len({k for k,v in rows})
        keys.update({k:json.loads(v) for k,v in rows})
    record=json.loads((ROOT/'制作源文件/事件文本_接入记录.json').read_text(encoding='utf-8'))
    assert len(record['events'])==12
    for entry in record['events']:
        event=entry['id'];text=keys[event+'.d']
        assert hashlib.sha256(text.encode()).hexdigest()==entry['desc_sha256']
        assert len(text.split('\n\n'))==entry['paragraphs']
        if entry['title']:assert keys[event+'.t']==entry['title']
        if entry['option']:assert keys[event+'.a']==entry['option']
        stack=[]
        for c in text:
            if c in '「『':
                assert c==('「' if not stack else '『')
                stack.append('」' if c=='「' else '』')
            elif c in '」』':assert stack.pop()==c
        assert not stack
    assert keys['gawed_yongdongbianqu.10.t']=='湾区的骑士'
    assert '『国王』' in keys['gcd_welyam.21.d'] and '『富商议会』' in keys['gcd_welyam.21.d']
    assert '1威利亚姆' not in keys['gcd_welyam.20.d']
    # 效果等游戏逻辑与填正文之前的提交逐项对比，只允许本次替换正文键和两个选项键。
    baseline='6a00d4288128975331b9c98a1b4d1eade6a8ad6a'
    for rel in ['events/gcd_welyam_reform_events.txt','events/gcd_yongdongbianqu_events.txt','events/gcd_celmaldor_events.txt']:
        old=parse(subprocess.check_output(['git','show',baseline+':'+rel],cwd=ROOT).decode('utf-8'))
        new=parse((ROOT/rel).read_text(encoding='utf-8-sig'))
        byid={e.scalar('id'):e for e in new.children('country_event')}
        for e in old.children('country_event'):
            current=byid[e.scalar('id')]
            for k in ['title','desc']:e.children(k)[0].value=current.children(k)[0].value
            for a,b in zip(e.children('option'),current.children('option')):
                a.children('name')[0].value=b.children('name')[0].value
        assert normalized(old)==normalized(new),rel
    print('Document event text validation passed: 12 texts/titles/options, paragraph counts, nested quotes, localisation roundtrip and unchanged event mechanics.')

if __name__=='__main__':validate()
