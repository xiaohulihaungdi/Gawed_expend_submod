"""校验克洛维剧情的占领边界、同场战争限制、灾难倒戈和事件时序；不启动游戏。"""
from __future__ import annotations
from pathlib import Path
from copy import deepcopy
import json
import sys

from pdx_script import parse, Node
from check_event_structure import errors

ROOT = Path(__file__).resolve().parent.parent


class Occupation:
    def __init__(self, triggers):
        self.triggers = triggers
        self.cb = "cb_gcd_adshaw_revolt"
        self.score = 0
        self.controllers = {p: "A13" for p in (221, 701, 737, 740, 700, 710)}
        self.provinces = {"Z26": [700, 710]}
        self.overlords = {"B00": "A13", "A24": "A13"}
        self.flags = {"gcd_crovis_revolt_active"}
        self.disaster = True
        self.liberty = 51

    def condition(self, n, actor="A13"):
        k, v = n.key, n.value
        if k in self.triggers:
            return all(self.condition(c, actor) for c in self.triggers[k].children())
        if k in {"AND", "limit", "trigger"}:
            return all(self.condition(c, actor) for c in n.children())
        if k == "OR": return any(self.condition(c, actor) for c in n.children())
        if k == "NOT": return not all(self.condition(c, actor) for c in n.children())
        if k == "has_country_flag": return v in self.flags
        if k == "tag": return actor == v
        if k == "exists": return v in {"Z26", "Z45", "A13", "A24"}
        if k == "is_subject_of": return self.overlords.get(actor) == v
        if k == "has_disaster": return self.disaster
        if k == "liberty_desire": return self.liberty >= float(v)
        if k == "is_in_war":
            if n.scalar('attacker_leader')=='THIS':
                return self.cb=='cb_crovis_invasion' and actor=='Z23' and n.scalar('defender_leader')=='Z18'
            return (self.cb == n.scalar("casus_belli") and
                    n.scalar("attacker_leader") == "Z45" and n.scalar("defender_leader") == "A13")
        if k == "war_score_against": return actor == "Z45" and n.scalar("who") == "A13" and self.score >= float(n.scalar("value"))
        if k == 'war_with': return actor=='Z23' and v=='Z18' and self.cb=='cb_crovis_invasion'
        if k == 'any_country': return any(all(self.condition(c,tag) for c in n.children()) for tag in ('A13','Z18','Z23','Z26'))
        if k.isdigit(): return all(self.condition(c, int(k)) for c in n.children())
        if k == "controller": return all(self.condition(c, self.controllers[actor]) for c in n.children())
        if k == "all_owned_province": return all(all(self.condition(c, p) for c in n.children()) for p in self.provinces[actor])
        if k in {"Z26", "Z45", "A24"}: return all(self.condition(c, k) for c in n.children())
        raise AssertionError((k, actor))


def validate():
    effects = parse((ROOT/'common/scripted_effects/gcd_crovis_effects.txt').read_text(encoding='utf-8'))
    triggers = {n.key:n for n in parse((ROOT/'common/scripted_triggers/gcd_crovis_triggers.txt').read_text(encoding='utf-8')).children()}
    crown, rebels = triggers['gcd_crovis_crown_won_trigger'], triggers['gcd_crovis_rebels_won_trigger']
    base=Occupation(triggers)
    assert base.condition(crown) and not base.condition(rebels)
    funding=deepcopy(base);funding.cb='cb_crovis_invasion';funding.flags.add('gcd_crovis_funded')
    assert funding.condition(triggers['gcd_crovis_departed_trigger'])
    funding.flags.remove('gcd_crovis_funded');assert not funding.condition(triggers['gcd_crovis_departed_trigger'])
    funding.flags.add('gcd_crovis_funded');funding.cb='cb_conquest';assert not funding.condition(triggers['gcd_crovis_departed_trigger'])
    for p in (701,737,740,700,710):
        model=deepcopy(base);model.controllers[p]='Z26'
        assert not model.condition(crown),p
    subject=deepcopy(base);subject.controllers[737]='B00';assert subject.condition(crown)
    for captor in ('Z26','Z45','A24','REB','X99'):
        for score in (74.999,75,100):
            model=deepcopy(base);model.controllers[221]=captor;model.score=score
            assert model.condition(rebels)==(captor in {'Z26','Z45'} and score>=75),(captor,score)
    for cb in ('cb_conquest','cb_gcd_gawedi_civil_war',''):
        model=deepcopy(base);model.cb=cb;model.controllers[221]='Z45';model.score=100
        assert not model.condition(crown) and not model.condition(rebels)
    hook=effects.children('gcd_crovis_westmoors_hook_effect')[0].children('if')[0].children('limit')[0]
    for disaster,ld,subject,expected in [(True,50,True,False),(True,50.001,True,True),(False,100,True,False),(True,100,False,False)]:
        model=deepcopy(base);model.disaster=disaster;model.liberty=ld
        if not subject:model.overlords.pop('A24')
        assert model.condition(hook)==expected,(disaster,ld,subject)

    event_tree=parse((ROOT/'events/gcd_yongdongbianqu_events.txt').read_text(encoding='utf-8'))
    events={e.scalar('id'):e for e in event_tree.children('country_event')}
    assert len(events)==10
    assert not errors(event_tree,effects)
    for eid,e in events.items():
        assert e.children('option')
        if eid!='gawed_yongdongbianqu.11': assert e.scalar('is_triggered_only')=='yes'
    def event(number):return events['gawed_yongdongbianqu.'+str(number)]
    assert event(2).children('immediate')[0].children('country_event')[0].scalar('days')=='180'
    assert event(2).children('immediate')[0].children('country_event')[0].scalar('id')=='gawed_yongdongbianqu.4'
    cultural=event(4).children('option')[0]
    assert {n.key for n in cultural.children() if n.key.isdigit()}=={'726','738','739','740','990'}
    assert all(n.children('change_culture')[0].value=='white_reachman' for n in cultural.children() if n.key.isdigit())
    assert cultural.children('country_event')[0].scalar('days')=='90'
    assert cultural.children('country_event')[0].scalar('id')=='gawed_yongdongbianqu.5'
    assert not event(6).children('hidden')
    assert [e.scalar('id') for e in events.values() if e.children('mean_time_to_happen')]==['gawed_yongdongbianqu.11']
    mods=parse((ROOT/'common/event_modifiers/gcd_yongdongbianqu_modifiers.txt').read_text(encoding='utf-8'))
    assert mods.children('gcd_crovis_funded_armies')[0].scalar('shock_damage_received')=='-0.15'
    assert mods.children('bumanderenmin')[0].scalar('global_unrest')=='2'
    finish=effects.children('gcd_crovis_crown_victory_effect')[0]
    assert {n.value for n in finish.walk() if n.key=='inherit'}=={'Z26','Z45'}
    assert finish.children('east_chillsbay_area')[0].children('add_core')[0].value=='A13'
    loss=effects.children('gcd_crovis_rebel_victory_effect')[0]
    assert loss.children('coast_of_vics_area')[0].children('cede_province')[0].value=='Z26'
    start=effects.children('gcd_crovis_start_revolt_effect')[0]
    assert len([n for n in start.walk() if n.key=='declare_war_with_cb'])==1
    assert not any(n.key=='declare_war' for n in start.walk())
    frozen=parse((ROOT/'events/Flavour_Frozenmaw_Z18.txt').read_text(encoding='utf-8'))
    restored=next(e for e in frozen.children('country_event') if e.scalar('id')=='flavor_frozenmaw.55').children('option')[0]
    assert restored.children('change_tag')[0].end<restored.children('gcd_crovis_after_restoration_effect')[0].start
    # 原文以段落分隔导出，所有五篇正文必须来自DOCX，不替换为早先聊天版本。
    source=(ROOT/'制作源文件/克洛维之歌_文档原文.txt').read_text(encoding='utf-8')
    loc=(ROOT/'制作源文件/永冻边区事件_中文原文.yml').read_text(encoding='utf-8')
    for number in (1,2,4,5,8):
        line=next(s for s in loc.splitlines() if s.startswith(f' gawed_yongdongbianqu.{number}.d:'))
        text=json.loads(line.split(':0 ',1)[1])
        assert all(p in source for p in text.split('\n\n'))
    print('Crovis validation passed: five texts, timings, occupation/score boundaries, same-war gates, Westmoors, rewards and native callback order.')


if __name__=='__main__':validate()
