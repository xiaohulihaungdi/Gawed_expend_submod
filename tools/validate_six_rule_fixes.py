"""覆盖开局禁令、永久宣称、40点边界、自治附庸、内战和平与延迟出征；只运行脚本模型。"""
from pathlib import Path
import argparse
from pdx_script import parse
from validate_reform import normalized
from validate_royal_monarchy import RoyalModel
from validate_royal_marriage import MarriageModel

ROOT=Path(__file__).resolve().parent.parent

class PauseModel(RoyalModel):
    def condition(self,n):
        if n.key=='exists':return n.value=='Z18'
        if n.key=='war_with' and n.value=='Z18':return False
        return super().condition(n)

def validate(anb):
    def read(path):return parse((ROOT/path).read_text(encoding='utf-8-sig'))
    effects={n.key:n for p in (ROOT/'common/scripted_effects').glob('*.txt') for n in parse(p.read_text(encoding='utf-8-sig')).children()}
    lock=effects['gcd_welyam_lock_burgher_loans_effect']
    for complete,ended,other_lock in [(False,False,False),(True,False,False),(False,True,False),(False,False,True)]:
        m=RoyalModel(effects)
        if complete:m.completed.add('a13_5_2')
        if ended:m.flags['gcd_welyam_reform_ended']=0
        if other_lock:m.flags['estate_burghers_indebted_to_burghers_disabled']=0
        m.execute(lock)
        assert ('gcd_welyam_owns_burgher_loan_lock' in m.flags)==(not complete and not ended and not other_lock)
        assert ('estate_burghers_indebted_to_burghers_disabled' in m.flags)==(other_lock or (not complete and not ended))
    assert any(n.key=='gcd_welyam_lock_burgher_loans_effect' for n in read('common/on_actions/gcd_welyam_on_actions.txt').children('on_startup')[0].walk())
    assert read('history/countries/A13 - Gawed.txt').children('gcd_welyam_lock_burgher_loans_effect')
    tasks={n.key:n for c in read('missions/a13_stage1_missions.txt').children() for n in c.children()}
    assert tasks['a13_1_1'].children('effect')[0].children('small_country_region')[0].scalar('add_permanent_claim')=='ROOT'
    reward=tasks['a13_3_4'].children('effect')[0]
    assert reward.children('add_country_modifier')[0].scalar('name')=='quanwanqudezhuren'
    assert len(reward.children())==2
    provinces=reward.children('every_province')[0]
    assert provinces.children('limit')[0].scalar('culture')=='gray_orc' and provinces.scalar('add_permanent_claim')=='ROOT'
    start=effects['gcd_welyam_start_civil_war_effect']
    assert start.children('set_country_flag')[0].value=='gcd_welyam_civil_war_starting'
    assert start.children('every_enemy_country')[0].end<next(n for n in start.walk() if n.key=='gcd_welyam_release_revolt_country_effect').start
    m=MarriageModel(effects);m.enemy_tags=['A01','X99'];m.execute(start)
    assert m.peaces[:2]==[('A13','A01'),('A13','X99')] and m.enemy_tags==[]
    assert 'gcd_welyam_civil_war_starting' not in m.flags and 'gcd_welyam_civil_war_active' in m.flags
    events={e.scalar('id'):e for e in read('events/gcd_yongdongbianqu_events.txt').children('country_event')}
    crowned=events['gawed_yongdongbianqu.2'].children('option')[0]
    assert next(n for n in crowned.walk() if n.key=='create_subject').scalar('subject_type')=='autonomous_vassal'
    assert next(n for n in crowned.walk() if n.key=='create_subject').scalar('subject')=='Z45'
    native=parse((anb/'events/Flavour_Frozenmaw_Z18.txt').read_text(encoding='utf-8-sig'))
    original=next(e for e in native.children('country_event') if e.scalar('id')=='flavor_frozenmaw.54').children('option')[0]
    frozen=read('events/Flavour_Frozenmaw_Z18.txt')
    option=next(e for e in frozen.children('country_event') if e.scalar('id')=='flavor_frozenmaw.54').children('option')[0]
    assert [normalized(n) for n in option.children('else')[0].children() if n.key!='gcd_crovis_on_restoration_war_effect']==[normalized(n) for n in original.children() if n.key!='name']
    for flag in ('gcd_welyam_civil_war_starting','gcd_welyam_civil_war_active'):
        m=PauseModel(effects);m.actor='Z23';m.flags[flag]=0;m.execute(option)
        assert 'gcd_crovis_departure_paused' in m.flags and not m.events
        resume=events['gawed_yongdongbianqu.12']
        assert not m.condition(resume.children('trigger')[0])
        m.flags.pop(flag)
        assert m.condition(resume.children('trigger')[0])
        m.execute(resume.children('option')[0])
        assert 'gcd_crovis_departure_paused' not in m.flags and m.events==['flavor_frozenmaw.54']
        assert not m.condition(resume.children('trigger')[0])
    print('Six-rule validation passed: day-zero loan lock, ownership-safe unlock, permanent/culture claims, autonomous subject, pre-civil-war peace, native departure preservation, pause and resume.')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('anb',type=Path);a=p.parse_args();validate(a.anb)
