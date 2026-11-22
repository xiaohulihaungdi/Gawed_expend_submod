"""从当前原版俄罗斯能力和Anbennar一级君主改革表生成加韦德专用版本。"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
from pdx_script import parse

ROOT = Path(__file__).resolve().parent.parent
TARGET = 'gcd_gawedi_monarchy'


def build(anb: Path, game: Path):
    government = anb/'common/governments/00_governments.txt'
    monarchy=parse(government.read_text(encoding='utf-8-sig')).children('monarchy')[0]
    level=monarchy.children('reform_levels')[0].children()[0]
    reforms=[n.key for n in level.children('reforms')[0].children()]
    assert len(reforms)==len(set(reforms)) and 'feudalism_reform' in reforms
    lines=['# 生成：只替换当前君主制第一层，保留其他层改革与改革点数。',
           'gcd_royal_install_tier1_effect = {',
           '    if = { limit = { NOT = { government = monarchy } } change_government = monarchy }',
           f'    if = {{ limit = {{ NOT = {{ has_reform = {TARGET} }} }}']
    for reform in reforms:
        if reform!=TARGET:
            lines.append(f'        if = {{ limit = {{ has_reform = {reform} }} remove_government_reform = {reform} }}')
    lines.extend([f'        add_government_reform = {TARGET}','    }','}',''])
    source=game/'common/government_mechanics/04_russian.txt'
    text=source.read_bytes().decode('utf-8-sig').replace('\r\n','\n')
    mapping={'russian_mechanic':'gcd_gawedi_mechanic',
             'russian_adm_power':'gcd_gawedi_adm_power','russian_dip_power':'gcd_gawedi_dip_power',
             'russian_mil_power':'gcd_gawedi_mil_power',
             'RUSABIL_SUDEBNIK_EFFECT_TT':'gcd_royal_autonomy_tt',
             'RUSABIL_SUDEBNIK':'GCD_GAWEDI_SEIZE_LORDS',
             'RUSABIL_OPRICHNINA':'GCD_GAWEDI_FUND_COUNCIL',
             'RUSABIL_STRELTSY':'GCD_GAWEDI_ROYAL_GUARD'}
    # 只替换完整标识符，避免连带改坏原生 russian_mechanics_interaction_gui 窗口名。
    for old,new in mapping.items():text=re.sub(r'\b'+re.escape(old)+r'\b',new,text)
    tree=parse(text).children()[0]
    available=tree.children('available')[0]
    military=tree.children('interactions')[0].children('GCD_GAWEDI_ROYAL_GUARD')[0].children('effect')[0]
    replacements=[(available,'available = { has_reform = gcd_gawedi_monarchy }'),
                  (military,'''effect = {
                # 用户新设计：一年人力和十年卫兵训练；不保留原俄军事项其他奖励。
                add_yearly_manpower = 1
                add_country_modifier = { name = gcd_royal_guard_training duration = 3650 }
            }''')]
    for n,new in sorted(replacements,key=lambda pair:pair[0].start,reverse=True):
        text=text[:n.start]+new+text[n.end:]
    text='# 生成：俄罗斯能力的加韦德专用副本；前两项效果不改，军事项按用户设计替换。\n'+text
    output={'common/scripted_effects/gcd_gawedi_tier1_effect.txt':'\n'.join(lines).encode('utf-8'),
            'common/government_mechanics/gcd_gawedi_monarchy.txt':text.encode('utf-8')}
    metadata={'tier1_source_sha256':hashlib.sha256(government.read_bytes()).hexdigest(),
              'russian_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'level':1,'level_key':level.key,'reforms':reforms,
              'generated_sha256':{p:hashlib.sha256(b).hexdigest() for p,b in output.items()}}
    return output,metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('anb_root',type=Path);parser.add_argument('game_root',type=Path)
    parser.add_argument('--check',action='store_true');args=parser.parse_args()
    output,metadata=build(args.anb_root,args.game_root)
    for path,data in output.items():
        target=ROOT/path
        if args.check:assert target.read_bytes()==data,path
        else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    if not args.check:(ROOT/'制作源文件/加韦德君主制_生成基线.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Gawedi government {"checked" if args.check else "generated"}: {len(metadata["reforms"])} tier-one choices, 3 abilities.')
