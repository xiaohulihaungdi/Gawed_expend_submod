"""运行婚约选择、修正归属及受保护属国的释放/参战边界模型；不启动游戏。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

from check_event_structure import errors
from pdx_script import Node, parse
from validate_reform import decode_special
from validate_royal_monarchy import RoyalModel
from validate_crovis import Occupation

ROOT = Path(__file__).resolve().parent.parent
LOYAL = 'gcd_marriage_westmoors_loyal'


class MarriageModel(RoyalModel):
    def __init__(self, effects):
        super().__init__(effects)
        self.year, self.month = 1450, 5
        self.loyalty = {'estate_nobles': 60, 'estate_burghers': 60}
        self.liberty = {'A24': 50, 'Z26': 50, 'Z45': 50}
        self.mods = {'A13': self.country_modifiers, 'A24': {}, 'Z26': {}, 'Z45': {}}
        self.overlords = {'A24': 'A13', 'Z26': 'A13', 'Z45': 'A13'}
        self.alive = {'A13', 'A24', 'Z26', 'Z45'}
        self.released, self.independent, self.joined = [], [], []
        self.released_all = False
        self.consort = None
        self.previous_actor = None

    def condition(self, n):
        k, v = n.key, n.value
        if k == 'is_year': return self.year >= int(v)
        if k == 'is_month': return self.month >= int(v)
        if re.fullmatch(r'[A-Z][0-9]{2}', k) or k == 'FROM':
            old = self.actor
            self.actor = self.target if k == 'FROM' else k
            result = all(self.condition(c) for c in n.children())
            self.actor = old
            return result
        if k == 'is_subject_of': return self.overlords.get(self.actor) == v
        if k == 'liberty_desire': return self.liberty[self.actor] >= float(v)
        if k == 'has_country_modifier': return v in self.mods.get(self.actor, {})
        if k == 'exists': return (self.actor in self.alive) == (v == 'yes') if v in {'yes', 'no'} else v in self.alive
        if k == 'is_emperor': return False
        return super().condition(n)

    def execute(self, block):
        branch = None
        for n in block.children():
            k, v = n.key, n.value
            if k == 'if':
                branch = self.condition(n.children('limit')[0])
                if branch: self.execute(n)
            elif k == 'else_if':
                if not branch and self.condition(n.children('limit')[0]):
                    self.execute(n)
                    branch = True
            elif k == 'else':
                if not branch: self.execute(n)
                branch = None
            elif re.fullmatch(r'[A-Z][0-9]{2}', k):
                old, previous = self.actor, self.previous_actor
                self.actor, self.previous_actor = k, old
                self.execute(n)
                self.actor, self.previous_actor = old, previous
            elif k == 'define_consort':
                self.consort = {c.key: c.value for c in n.children()}
            elif k == 'add_estate_loyalty':
                self.loyalty[n.scalar('estate')] += float(n.scalar('loyalty'))
            elif k == 'add_liberty_desire':
                self.liberty[self.actor] = max(0, min(100, self.liberty[self.actor]+float(v)))
            elif k == 'add_country_modifier':
                self.mods.setdefault(self.actor, {})[n.scalar('name')] = int(n.scalar('duration'))
            elif k == 'remove_country_modifier':
                self.mods.setdefault(self.actor, {}).pop(v, None)
                if self.actor == 'A13': self.ruler_modifiers.discard(v)
            elif k == 'every_subject_country':
                old = self.actor
                for tag, overlord in list(self.overlords.items()):
                    if overlord != old: continue
                    self.actor = tag
                    if not n.children('limit') or self.condition(n.children('limit')[0]): self.execute(n)
                self.actor = old
            elif k == 'every_owned_province':
                self.execute(n) # 此模型扫描一块带A24/X01/X02核心的自有省份。
            elif k == 'every_core_country':
                old = self.actor
                for tag in ('A24', 'X01', 'X02'):
                    self.actor = tag
                    if self.condition(n.children('limit')[0]): self.execute(n)
                self.actor = old
            elif k == 'release':
                assert self.actor == 'A13' and v == 'PREV'
                self.released.append(self.previous_actor)
                self.alive.add(self.previous_actor)
                self.overlords[self.previous_actor] = 'A13'
            elif k == 'grant_independence':
                self.independent.append(self.actor)
                self.overlords.pop(self.actor, None)
            elif k == 'release_all_possible_countries':
                self.released_all = True
                for tag in ('X01', 'X02'):
                    self.released.append(tag)
                    self.overlords[tag] = 'A13'
                    self.alive.add(tag)
            elif k == 'gcd_welyam_release_revolt_country_effect':
                # 旧指定国家释放效果未改；此处记录真实调用参数，核对新保护分支有没有跳过A24。
                tag = n.scalar('REBEL_TAG')
                self.released.append(tag)
                self.alive.add(tag)
                self.overlords.pop(tag, None)
            elif k == 'gcd_welyam_join_civil_war_effect':
                self.joined.append(n.scalar('REBEL_TAG'))
            elif k == 'declare_war_with_cb':
                assert n.scalar('who') == 'A13'
            else:
                super().execute(Node('ROOT', [n], 0, 0))


def validate(anb: Path, game: Path):
    def read(path): return parse((ROOT/path).read_text(encoding='utf-8-sig'))
    effects = {n.key: n for file in (ROOT/'common/scripted_effects').glob('*.txt')
               for n in parse(file.read_text(encoding='utf-8-sig')).children()}
    tree = read('events/gcd_royal_marriage_events.txt')
    events = {n.scalar('id'): n for n in tree.children('country_event')}
    marriage, migration = events['gcd_marriage.1'], events['gcd_marriage.2']
    assert not errors(tree, Node('ROOT', list(effects.values()), 0, 0))
    assert marriage.scalar('fire_only_once') == 'yes' and marriage.children('mean_time_to_happen')[0].scalar('days') == '1'
    for year, month, expected in [(1449, 5, False), (1450, 4, False), (1450, 5, True),
                                  (1450, 7, True), (1450, 8, False), (1451, 5, False)]:
        model = MarriageModel(effects)
        model.year, model.month = year, month
        assert model.condition(marriage.children('trigger')[0]) == expected
    options = marriage.children('option')
    first, lords, moors = [MarriageModel(effects) for _ in range(3)]
    for model, option in zip((first, lords, moors), options):
        model.execute(option)
        assert not model.condition(marriage.children('trigger')[0])
    assert first.ruler_modifiers == {'gcd_marriage_queen_karina'} and first.events == ['flavor_gawed.35']
    assert first.loyalty == {'estate_nobles': 50, 'estate_burghers': 60} and first.liberty['A24'] == 65
    assert lords.consort == {'culture': 'gawedi', 'female': 'yes'} and lords.loyalty['estate_burghers'] == 50
    assert lords.ruler_modifiers == {'gcd_marriage_great_lords'}
    assert moors.consort == {'culture': 'moorman', 'female': 'yes'} and moors.liberty['A24'] == 20 and LOYAL in moors.flags
    for option in options:
        for mod in (n for n in option.walk() if n.key == 'add_ruler_modifier'): assert mod.scalar('duration') == '-1'
    mods = read('common/event_modifiers/gcd_royal_marriage_modifiers.txt')
    assert {n.key: n.value for n in mods.children('gcd_marriage_queen_karina')[0].children()} == {'monarch_lifespan': '0.15', 'global_autonomy': '-0.05'}
    assert {n.key: n.value for n in mods.children('gcd_marriage_great_lords')[0].children()} == {
        'nobles_loyalty_modifier': '0.15', 'nobles_influence_modifier': '0.10', 'global_autonomy': '0.05'}
    assert not any(n.key == 'clr_country_flag' and n.value == LOYAL for effect in effects.values() for n in effect.walk())
    assert not {n.key for n in mods.children()} & {n.value for n in effects['gcd_welyam_cleanup_reform_effect'].walk() if n.key == 'remove_country_modifier'}

    # 执行实际内战启动AST：有婚约时，指定释放、全体释放、属国独立、参战四步都必须保留A24。
    for loyal in (False, True):
        model = MarriageModel(effects)
        if loyal: model.flags[LOYAL] = model.day
        model.execute(effects['gcd_welyam_start_civil_war_effect'])
        assert ('A24' in model.released) == (not loyal)
        assert ('A24' in model.joined) == (not loyal)
        assert (model.overlords.get('A24') == 'A13') == loyal
        assert {'X01', 'X02'} <= set(model.released) and not {'X01', 'X02'} & model.overlords.keys()
        assert model.released_all == (not loyal)
    # 受保护的“尚未存在的A24”也不能从加韦德核心领土被再次释放。
    dead = MarriageModel(effects)
    dead.alive.remove('A24')
    dead.flags[LOYAL] = 0
    dead.execute(effects['gcd_marriage_release_other_countries_effect'])
    assert 'A24' not in dead.released
    protected = MarriageModel(effects)
    protected.flags[LOYAL] = 0
    protected.execute(effects['gcd_welyam_crown_victory_effect'])
    assert 'A24' not in protected.inherited
    protected.execute(effects['gcd_welyam_westmoors_defect_effect'])
    assert protected.overlords['A24'] == 'A13' and not protected.events
    external = effects['gcd_welyam_on_declare_war_effect'].children('if')[0].children('limit')[0]
    model = MarriageModel(effects)
    model.liberty['A24'] = 100
    assert model.condition(external)
    model.flags[LOYAL] = 0
    assert not model.condition(external)
    crovis = {n.key: n for n in read('common/scripted_triggers/gcd_crovis_triggers.txt').children()}
    model = Occupation(crovis)
    hook = effects['gcd_crovis_westmoors_hook_effect'].children('if')[0].children('limit')[0]
    assert model.condition(hook)
    model.flags.add(LOYAL)
    assert not model.condition(hook)
    actions = read('common/diplomatic_actions/00_diplomatic_actions.txt')
    lock = next(n for n in actions.children('declarewar')[0].children('condition') if n.scalar('tooltip') == 'gcd_marriage_moorman_war_lock_tt')
    model = MarriageModel(effects)
    model.actor, model.target = 'A24', 'A13'
    model.flags[LOYAL] = 0
    assert model.condition(lock.children('potential')[0]) and not model.condition(lock.children('allow')[0])
    model.target = 'A01'
    assert not model.condition(lock.children('potential')[0])

    # 真正执行宽宥选项：独立倾向给两国，十年叛乱修正只给A13。
    mercy = next(n for n in read('events/gcd_yongdongbianqu_events.txt').children('country_event') if n.scalar('id') == 'gawed_yongdongbianqu.5').children('option')[1]
    model = MarriageModel(effects)
    model.execute(mercy)
    assert model.liberty['Z26'] == model.liberty['Z45'] == 40
    assert model.mods['A13'] == {'bumanderenmin': 3650} and not model.mods['Z26'] and not model.mods['Z45']
    for correct in (False, True):
        model = MarriageModel(effects)
        model.flags['gcd_crovis_frida_spared'] = 0
        model.mods['Z26']['bumanderenmin'] = model.mods['Z45']['bumanderenmin'] = 2000
        if correct: model.mods['A13']['bumanderenmin'] = 1000
        assert model.condition(migration.children('trigger')[0])
        model.execute(migration.children('option')[0])
        assert not model.mods['Z26'] and not model.mods['Z45']
        assert model.mods['A13']['bumanderenmin'] == (1000 if correct else 3650)
        assert not model.condition(migration.children('trigger')[0])

    native = {n.scalar('id'): n for n in read('events/Flavour_Gawed_A13.txt').children('country_event')}
    advisor = native['flavor_gawed.4'].children('option')[0].children('define_advisor')[0]
    assert {n.key: n.value for n in advisor.children()} == {'type': 'trader', 'name': 'Derek Deland', 'skill': '2', 'cost_multiplier': '0.25'}
    assert not native['flavor_gawed.35'].children('trigger') and native['flavor_gawed.35'].scalar('is_triggered_only') == 'yes'
    assert native['flavor_gawed.35'].children('option')[0].children('define_consort')[0].scalar('name') == 'Karina'
    source = (ROOT/'制作源文件/王冠与婚约_中文原文.yml').read_text(encoding='utf-8-sig')
    runtime = (ROOT/'localisation/gcd_royal_marriage_l_english.yml').read_text(encoding='utf-8-sig')
    assert decode_special(runtime) == source
    keys = re.findall(r'^\s*([\w.]+):\d+ ', source, re.M)
    assert len(keys) == len(set(keys))
    desc = json.loads(next(line for line in source.splitlines() if line.startswith(' gcd_marriage.1.d:')).split(':0 ', 1)[1])
    assert len(desc.split('\n\n')) == 4
    for n in tree.walk():
        if n.key in {'title', 'desc', 'name', 'custom_tooltip'} and isinstance(n.value, str) and n.value.startswith('gcd_marriage'):
            assert n.value in keys or mods.children(n.value)
    # 原版文化文件为传统单字节编码；只读取ASCII文化标识符，勿按UTF-8强行解码。
    cultures = parse((anb/'common/cultures/anb_cultures.txt').read_bytes().decode('latin1'))
    assert {'gawedi', 'moorman'} <= {n.key for n in cultures.walk()}
    assert 'trader' in {n.key for n in parse((game/'common/advisortypes/00_advisortypes.txt').read_text(encoding='utf-8-sig')).children()}
    print('Marriage validation passed: summer/date limits, three choices, native event/advisor, permanent loyalty, civil-war releases/victory, all defection hooks, mercy scope, old saves and localisation.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('anb_root', type=Path)
    parser.add_argument('game_root', type=Path)
    args = parser.parse_args()
    validate(args.anb_root, args.game_root)
