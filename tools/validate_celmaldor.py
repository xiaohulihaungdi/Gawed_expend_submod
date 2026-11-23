"""检查凯尔马尔多事件链的归属、计时、人口档位及广播对象，不启动游戏。"""
from pathlib import Path
import argparse
import re
from pdx_script import parse, Node
from check_event_structure import errors
from validate_reform import decode_special

ROOT = Path(__file__).resolve().parent.parent

class Model:
    def __init__(self, eligible):
        self.eligible = eligible
        self.day = 0
        self.owner, self.subject, self.kind = 'A13', False, 'vassal'
        self.actor, self.flags, self.queue = 'A13', {}, []
        self.dev, self.devastation, self.pop = [8, 8, 4], 0, 3
        self.culture = 'moon_elf'
        self.modifiers = {}
    def condition(self, n):
        k, v = n.key, n.value
        if k in {'trigger', 'limit', 'AND', '696', 'NOT', 'OR'}:
            values = [self.condition(c) for c in n.children()]
            return any(values) if k == 'OR' else not all(values) if k == 'NOT' else all(values)
        if k == 'gcd_celmaldor_eligible_owner_trigger': return all(self.condition(c) for c in self.eligible.children())
        if k == 'owned_by': return self.owner == v
        if k == 'owner': return all(self.condition(c) for c in n.children())
        if k == 'is_subject_of': return self.subject and v == 'A13'
        if k == 'is_subject_of_type': return self.kind == v
        if k == 'tag': return self.actor == v
        if k == 'exists': return v == 'A21'
        if k == 'has_province_flag': return v in self.flags
        if k == 'had_province_flag': return n.scalar('flag') in self.flags and self.day-self.flags[n.scalar('flag')] >= int(n.scalar('days'))
        if k == 'has_elven_majority_trigger': return self.pop == 3
        if k == 'has_any_elven_pop_trigger': return self.pop > 0
        raise AssertionError(k)
    def execute(self, block):
        for n in block.children():
            k, v = n.key, n.value
            if k in {'name', 'limit'}: continue
            if k == 'if':
                if self.condition(n.children('limit')[0]): self.execute(n)
            elif k == '696': self.execute(n)
            elif k == 'A21':
                old = self.actor
                self.actor = 'A21'
                self.execute(n)
                self.actor = old
            elif k == 'set_province_flag': self.flags[v] = self.day
            elif k == 'change_culture': self.culture = v
            elif k == 'convert_majority_to_minority':
                if self.pop == 3 and self.culture == 'blue_reachman': self.pop = 2
            elif k == 'remove_elven_minority_size_effect': self.pop = max(0, self.pop-1)
            elif k == 'remove_racial_minority_any_size':
                assert n.scalar('race') == 'elven'
                self.pop = 0
            elif k in {'add_base_tax', 'add_base_production', 'add_base_manpower'}:
                i = ['add_base_tax', 'add_base_production', 'add_base_manpower'].index(k)
                self.dev[i] = max(1, self.dev[i]+int(v))
            elif k == 'add_devastation': self.devastation += int(v)
            elif k == 'country_event': self.queue.append((self.actor, n.scalar('id'), int(n.scalar('days'))))
            elif k == 'add_country_modifier': self.modifiers[self.actor] = (n.scalar('name'), n.scalar('duration'))
            else: raise AssertionError(k)

def validate(anb, game):
    def read(path): return parse((ROOT/path).read_text(encoding='utf-8-sig'))
    tree = read('events/gcd_celmaldor_events.txt')
    events = {e.scalar('id'): e for e in tree.children('country_event')}
    assert len(events) == 4 and not errors(tree, Node('ROOT', [], 0, 0))
    eligible = read('common/scripted_triggers/gcd_celmaldor_triggers.txt').children()[0]
    first, second, third, refugee = [events[f'gcd_celmaldor.{i}'] for i in range(1, 5)]
    for owner, subject, kind, expected in [('A13',False,'vassal',True),('X01',True,'vassal',True),
        ('X01',True,'tributary_state',False),('X01',True,'tributary_state_anb',False),('X01',False,'vassal',False)]:
        m = Model(eligible)
        m.owner, m.subject, m.kind = owner, subject, kind
        assert m.condition(first.children('trigger')[0]) == expected
    m = Model(eligible)
    m.execute(first.children('option')[0])
    assert m.culture == 'blue_reachman' and m.dev == [7,7,3] and m.devastation == 20 and m.pop == 2
    assert m.queue == [('A13','gcd_celmaldor.2',365), ('A21','gcd_celmaldor.4',1)]
    for day, expected in [(364,False),(365,True)]:
        m.day = day
        assert m.condition(second.children('trigger')[0]) == expected
    m.owner = 'X01'
    assert not m.condition(second.children('trigger')[0])
    m.owner = 'A13'
    m.execute(second.children('immediate')[0])
    assert not m.condition(second.children('trigger')[0])
    m.execute(second.children('option')[0])
    assert m.pop == 1 and m.dev == [6,6,2] and m.queue[-1] == ('A13','gcd_celmaldor.3',730)
    for day, expected in [(1094,False),(1095,True)]:
        m.day = day
        assert m.condition(third.children('trigger')[0]) == expected
    m.execute(third.children('immediate')[0])
    assert not m.condition(third.children('trigger')[0])
    m.execute(third.children('option')[0])
    assert m.pop == 0 and m.dev == [5,5,1] and m.devastation == 20
    assert not m.condition(third.children('trigger')[0])
    m.actor = 'A21'
    assert m.condition(refugee.children('trigger')[0])
    m.execute(refugee.children('immediate')[0])
    assert m.modifiers == {'A21': ('gcd_celmaldor_elven_refugees','-1')}
    assert refugee.scalar('major') == 'yes' and refugee.children('major_trigger')[0].scalar('tag') == 'A13'
    mod = read('common/event_modifiers/gcd_celmaldor_modifiers.txt').children()[0]
    assert {n.key:n.value for n in mod.children()} == {'colonists':'1','colonial_range':'0.30','global_colonial_growth':'10'}
    task = next(n for c in read('missions/a13_stage1_missions.txt').children() for n in c.children() if n.key == 'a13_4_4')
    for pop in (0,1,2,3):
        m.pop = pop
        assert m.condition(task.children('trigger')[0]) == (pop == 0)
    native = (anb/'common/scripted_effects/anb_scripted_effects_for_racial_tolerances.txt').read_text(encoding='utf-8-sig')
    for name in ['remove_elven_minority_size_effect', 'remove_racial_minority_any_size', 'convert_majority_to_minority']:
        assert re.search(r'^'+name+r'\s*=',native,re.M)
    racial = (anb/'common/scripted_triggers/anb_scripted_triggers_racial.txt').read_text(encoding='utf-8-sig')
    assert 'has_any_elven_pop_trigger = {' in racial
    gfx = '\n'.join(p.read_text(encoding='utf-8-sig', errors='replace') for root in (anb,game) for p in (root/'interface').rglob('*.gfx'))
    for e in events.values(): assert e.scalar('picture') in gfx, e.scalar('picture')
    source = (ROOT/'制作源文件/凯尔马尔多_中文原文.yml').read_text(encoding='utf-8-sig')
    assert decode_special((ROOT/'localisation/gcd_celmaldor_l_english.yml').read_text(encoding='utf-8-sig')) == source
    for i in range(1,5):
        assert f' gcd_celmaldor.{i}.d:0 ""' in source and f' gcd_celmaldor.{i}.t:0 ""' in source
    print('Celmaldor validation passed: eligible owners/tributaries, 365/730-day boundaries, population stages, lost province, development, A21-only permanent reward/broadcast, mission, native interfaces and encoding.')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('anb',type=Path); p.add_argument('game',type=Path)
    a=p.parse_args();validate(a.anb,a.game)
