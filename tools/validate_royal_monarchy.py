"""检查王室胜利、政改替换、议案决议与一次性中立的实际脚本边界，不运行游戏。"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from build_gawedi_government import build
from check_event_structure import errors as event_errors
from pdx_script import Node, parse
from validate_reform import decode_special, normalized
from validate_welyam_units_and_reforms import Model

ROOT = Path(__file__).resolve().parent.parent


class RoyalModel(Model):
    def __init__(self, effects):
        super().__init__(effects, {})
        self.actor, self.target = 'A13', 'A01'
        self.scope = None
        self.war, self.civil_war, self.wex_in_target = False, True, False
        self.inherited, self.peaces, self.manpower = [], [], 0
        self.completed = set()
        self.parliament, self.debate, self.agendas = True, True, 2
        self.provinces = [dict(autonomy=30, seat=True, support=False),
                          dict(autonomy=5, seat=True, support=True),
                          dict(autonomy=20, seat=False, support=False)]

    def condition(self, node):
        k, v = node.key, node.value
        if k in {'potential', 'allow', 'ROOT', 'custom_trigger_tooltip'}:
            return all(self.condition(n) for n in node.children() if n.key != 'tooltip')
        if k in {'A13', 'A30', 'FROM'}:
            old = self.actor
            self.actor = self.target if k == 'FROM' else k
            result = all(self.condition(n) for n in node.children())
            self.actor = old
            return result
        if k == 'tag':
            return self.actor == v
        if k == 'had_country_flag':
            return v is not None and node.scalar('flag') in self.flags and self.day-self.flags[node.scalar('flag')] >= int(node.scalar('days'))
        if k == 'has_country_modifier':
            return v in self.country_modifiers or v in self.ruler_modifiers
        if k == 'war_with':
            return self.war if v == 'A01' else self.civil_war if v == 'A50' else False
        if k == 'is_in_war':
            return (self.wex_in_target and self.actor == 'A30'
                    and node.scalar('attacker_leader') == 'A13' and node.scalar('defender_leader') == 'A01')
        if k == 'mission_completed':
            return v in self.completed
        if k == 'gcd_welyam_has_karina_trigger':
            return False # 此模型默认没有卡琳娜配偶，数值分支另由改革检查覆盖。
        if k == 'any_owned_province':
            old = self.scope
            result = False
            for index in range(len(self.provinces)):
                self.scope = index
                result |= all(self.condition(n) for n in node.children())
            self.scope = old
            return result
        if k == 'local_autonomy_above_min':
            return self.provinces[self.scope]['autonomy'] >= float(v)
        if k in {'has_seat_in_parliament', 'is_backing_current_issue'}:
            field = 'seat' if k == 'has_seat_in_parliament' else 'support'
            return self.provinces[self.scope][field] == (v == 'yes')
        if k in {'has_parliament', 'has_active_debate', 'has_any_active_estate_agenda'}:
            return {'has_parliament': self.parliament, 'has_active_debate': self.debate,
                    'has_any_active_estate_agenda': bool(self.agendas)}[k] == (v == 'yes')
        if k == 'always':
            return v == 'yes'
        return super().condition(node)

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
            elif k == 'end_disaster':
                assert v == 'gcd_welyam_reform'
                self.disaster = False
            elif k == 'remove_country_modifier':
                self.country_modifiers.pop(v, None)
                self.ruler_modifiers.discard(v)
            elif k == 'change_government':
                self.gov = v
            elif k == 'inherit':
                self.inherited.append(v)
            elif k == 'complete_mission':
                self.completed.add(v)
            elif k == 'white_peace':
                self.peaces.append((self.actor, v))
                if self.actor == 'A30': self.wex_in_target = False
                elif v == 'A50': self.civil_war = False
            elif k in {'221', 'A30'}:
                old = self.actor
                self.actor = k
                self.execute(n)
                self.actor = old
            elif k in {'add_province_triggered_modifier', 'remove_province_triggered_modifier', 'clr_province_flag',
                       'change_government_reform_progress', 'add_treasury'}:
                pass
            elif k == 'every_owned_province':
                old = self.scope
                for index in range(len(self.provinces)):
                    self.scope = index
                    if not n.children('limit') or self.condition(n.children('limit')[0]): self.execute(n)
                self.scope = old
            elif k == 'add_local_autonomy_no_authority_effect':
                self.provinces[self.scope]['autonomy'] = max(0, self.provinces[self.scope]['autonomy']+float(v))
            elif k == 'auto_complete_estate_agenda':
                assert n.scalar('estate') == 'all'
                self.agendas = 0
            elif k == 'back_current_issue':
                self.provinces[self.scope]['support'] = True
            elif k == 'add_yearly_manpower':
                self.manpower += float(v)
            elif k == 'add_estate_loyalty' and n.scalar('estate') == 'all':
                self.noble_loyalty += float(n.scalar('loyalty'))
            else:
                super().execute(Node('ROOT', [n], 0, 0))


def validate(anb: Path, game: Path):
    def read(path): return parse((ROOT/path).read_text(encoding='utf-8-sig'))
    effects = {n.key: n for f in (ROOT/'common/scripted_effects').glob('*.txt')
               for n in parse(f.read_text(encoding='utf-8-sig')).children()}
    mods = {n.key: n for n in read('common/event_modifiers/gcd_royal_monarchy_modifiers.txt').children()}
    old_mods = {n.key for n in read('common/event_modifiers/gcd_welyam_reform_modifiers.txt').children()}
    assert {n.key: n.value for n in mods['gcd_royal_victory'].children()} == {
        'nobles_influence_modifier': '-0.20', 'global_autonomy': '-0.10',
        'land_maintenance_modifier': '-0.20', 'global_tax_modifier': '0.20'}
    assert {n.key: n.value for n in mods['gcd_royal_guard_training'].children()} == {
        'land_maintenance_modifier': '-0.10', 'discipline': '0.05'}

    # 真实胜利结算：仅删除灾难专属修正，保留君主/定期修正，自动完成五项任务且不重发奖励。
    winner = RoyalModel(effects)
    winner.country_modifiers = {name: -1 for name in old_mods} | {'unrelated_reward': 999}
    winner.ruler_modifiers = {'gcd_welyam_first_council', 'gcd_welyam_noble_settlement'}
    winner.flags.update({name: 0 for name in ('gcd_welyam_civil_war_active', 'gcd_welyam_daily_pulse_installed',
        'gcd_welyam_low_nobles_since', 'gcd_welyam_rebel_clock', 'gcd_welyam_fixed_rebels_due',
        'gcd_welyam_rebel_event_queued', 'gcd_welyam_owns_burgher_loan_lock', 'estate_burghers_indebted_to_burghers_disabled')})
    winner.reforms = {'feudalism_reform', 'empower_magnate_council', 'expanded_royal_court_reform'}
    winner.execute(effects['gcd_welyam_crown_victory_effect'])
    assert not winner.disaster and winner.ruler_modifiers == {'gcd_welyam_first_council', 'gcd_welyam_noble_settlement'}
    assert winner.country_modifiers == {name:-1 for name in old_mods if name != 'gcd_welyam_royal_right_hand'} | {'unrelated_reward':999, 'gcd_royal_victory':10950}
    assert winner.completed == {f'a13_5_{i}' for i in range(1,6)} and not winner.events
    assert winner.noble_land == 15 and winner.crown_land == 40
    assert winner.reforms == {'gcd_gawedi_monarchy', 'empower_magnate_council', 'expanded_royal_court_reform'}
    assert set(winner.inherited) == {'A50', 'B83', 'B84', 'A52', 'A51', 'A24'}
    assert not {'gcd_welyam_daily_pulse_installed', 'gcd_welyam_low_nobles_since', 'gcd_welyam_rebel_clock',
        'gcd_welyam_fixed_rebels_due', 'gcd_welyam_rebel_event_queued', 'estate_burghers_indebted_to_burghers_disabled'} & winner.flags.keys()
    winner.day += 100
    winner.execute(effects['gcd_royal_finish_reform_victory_effect'])
    assert winner.noble_land == 15 and winner.country_modifiers['gcd_royal_victory'] == 10950

    output, metadata = build(anb, game)
    for path, data in output.items(): assert (ROOT/path).read_bytes() == data, path
    for chosen in metadata['reforms']:
        state = RoyalModel(effects)
        state.reforms = {chosen, 'empower_magnate_council', 'expanded_royal_court_reform'}
        state.execute(effects['gcd_royal_install_tier1_effect'])
        assert state.reforms == {'gcd_gawedi_monarchy', 'empower_magnate_council', 'expanded_royal_court_reform'}, chosen
    reform = read('common/government_reforms/gcd_gawedi_monarchy.txt').children()[0]
    assert reform.scalar('has_parliament') == 'yes'
    assert reform.children('custom_attributes')[0].scalar('enables_estate_nobles') == 'yes'
    assert {n.key: n.value for n in reform.children('modifiers')[0].children()} == {
        'nobles_influence_modifier': '-0.10', 'burghers_loyalty_modifier': '0.10',
        'stability_cost_modifier': '-0.20', 'advisor_cost': '-0.10'}
    tier1 = read('common/governments/00_governments.txt').children('monarchy')[0].children('reform_levels')[0].children()[0]
    assert any(n.key == 'gcd_gawedi_monarchy' for n in tier1.children('reforms')[0].children())

    # 比较原生前两项全部效果，并核对三项沿用的窗口确实存在；防止替换标识符时误改窗口名。
    native = parse((game/'common/government_mechanics/04_russian.txt').read_text(encoding='utf-8-sig')).children()[0]
    mechanic = read('common/government_mechanics/gcd_gawedi_monarchy.txt').children()[0]
    interactions = mechanic.children('interactions')[0].children()
    for old, new in zip(native.children('interactions')[0].children()[:2], interactions[:2]):
        expected = normalized(old.children('effect')[0])
        if old.key == 'RUSABIL_SUDEBNIK':
            expected = normalized(parse(re.sub(r'\bRUSABIL_SUDEBNIK_EFFECT_TT\b', 'gcd_royal_autonomy_tt',
                (game/'common/government_mechanics/04_russian.txt').read_text(encoding='utf-8-sig'))).children()[0].children('interactions')[0].children()[0].children('effect')[0])
        assert normalized(new.children('effect')[0]) == expected
    for interaction in interactions:
        assert interaction.scalar('gui') == 'russian_mechanics_interaction_gui'
        assert interaction.scalar('cost') == '100'
    assert 'russian_mechanics_interaction_gui' in (anb/'interface/government_mechanics/russian_mechanics.gui').read_text(encoding='utf-8-sig')
    guard = RoyalModel(effects)
    guard.execute(interactions[2].children('effect')[0])
    assert guard.manpower == 1 and guard.country_modifiers == {'gcd_royal_guard_training': 3650}

    # 决议仅开放给新政改；检查冷却第3649/3650天，所有议席、议案和省份均受效。
    decision = read('decisions/gcd_royal_decrees.txt').children()[0].children()[0]
    decree = RoyalModel(effects)
    assert not decree.condition(decision.children('potential')[0])
    decree.reforms.add('gcd_gawedi_monarchy')
    assert decree.condition(decision.children('potential')[0])
    assert decree.condition(decision.children('allow')[0])
    decree.execute(decision.children('effect')[0])
    assert [p['autonomy'] for p in decree.provinces] == [15, 0, 5]
    assert all(p['support'] for p in decree.provinces if p['seat']) and decree.agendas == 0
    decree.day += 3649
    assert not decree.condition(decision.children('allow')[0])
    decree.day += 1
    assert decree.condition(decision.children('allow')[0])

    # 只有A13主动对A01宣战消耗一次；无关宣战不消耗，不含任何解除/重建同盟效果。
    wex = RoyalModel(effects)
    wex.execute(effects['gcd_wex_arm_neutrality_effect'])
    assert 'gcd_royal_pulse_installed' not in wex.flags
    for actor, target in [('A13', 'A99'), ('A99', 'A01')]:
        wex.actor, wex.target = actor, target
        wex.execute(effects['gcd_royal_before_declare_war_effect'])
        assert 'gcd_wex_neutrality_ready' in wex.flags
    wex.actor, wex.target = 'A13', 'A01'
    wex.execute(effects['gcd_royal_before_declare_war_effect'])
    assert 'gcd_wex_neutrality_ready' not in wex.flags and 'gcd_wex_neutrality_consumed' in wex.flags
    actions = read('common/diplomatic_actions/00_diplomatic_actions.txt')
    lock = next(n for n in actions.children('callaction')[0].children('condition') if n.scalar('tooltip') == 'gcd_wex_neutrality_call_tt')
    wex.actor, wex.target = 'A01', 'A30'
    assert wex.condition(lock.children('potential')[0]) and not wex.condition(lock.children('allow')[0])
    wex.target = 'A99'
    assert not wex.condition(lock.children('potential')[0])
    wex.actor = 'A13'
    wex.war, wex.wex_in_target = True, True
    wex.execute(effects['gcd_wex_enforce_neutrality_effect'])
    assert wex.peaces == [('A30', 'A13')] and wex.war
    wex.execute(effects['gcd_wex_enforce_neutrality_effect'])
    assert len(wex.peaces) == 1
    wex.war, wex.day = False, wex.day+1
    wex.execute(effects['gcd_royal_daily_effect'])
    assert 'gcd_wex_neutrality_active' not in wex.flags and 'gcd_royal_pulse_installed' not in wex.flags
    wex.execute(effects['gcd_wex_arm_neutrality_effect'])
    assert 'gcd_wex_neutrality_ready' not in wex.flags
    assert not any('alliance' in n.key for name, effect in effects.items() if name.startswith(('gcd_wex_', 'gcd_royal_before_')) for n in effect.walk())

    events = read('events/gcd_royal_monarchy_events.txt')
    assert not event_errors(events, Node('ROOT', list(effects.values()), 0, 0))
    migration = next(e for e in events.children('country_event') if e.scalar('id') == 'gcd_royal.1')
    old = RoyalModel(effects)
    old.completed.add('a13_2_1')
    assert old.condition(migration.children('trigger')[0])
    old.execute(migration.children('option')[0])
    assert 'gcd_wex_neutrality_ready' in old.flags and 'gcd_royal_victory' not in old.country_modifiers
    for event in read('events/gcd_welyam_reform_events.txt').children('country_event'):
        if event.scalar('id') in {'gcd_welyam.10', 'gcd_welyam.20', 'gcd_welyam.21', 'gcd_welyam.30'}:
            late = RoyalModel(effects)
            late.disaster = False
            late.execute(event.children('option')[0])
            assert late.country_modifiers or late.ruler_modifiers

    # 正常任务路线不要求赢内战；旧档两种完成方式均补上缺失效果而不再次没收土地。
    tasks = read('missions/a13_stage1_missions.txt')
    last = next(n for col in tasks.children() for n in col.children() if n.key == 'a13_5_5')
    peaceful = RoyalModel(effects)
    peaceful.completed.add('a13_5_5')
    peaceful.execute(last.children('effect')[0])
    assert 'gcd_gawedi_monarchy' in peaceful.reforms and peaceful.noble_land == 35
    assert peaceful.condition(reform.children('potential')[0])
    compat = next(e for e in events.children('country_event') if e.scalar('id') == 'gcd_royal.2')
    for won in (True, False):
        state = RoyalModel(effects)
        if won: state.flags['gcd_welyam_crown_victory_achieved'] = 0
        else: state.completed.add('a13_5_5')
        assert state.condition(compat.children('trigger')[0])
        state.execute(compat.children('option')[0])
        assert 'gcd_gawedi_monarchy' in state.reforms and state.noble_land == 35 and not state.country_modifiers
        if won: assert state.completed == {f'a13_5_{i}' for i in range(1,6)}
        assert not state.condition(compat.children('trigger')[0])

    source = (ROOT/'制作源文件/加韦德君主制_中文原文.yml').read_text(encoding='utf-8-sig')
    runtime = (ROOT/'localisation/gcd_gawedi_monarchy_l_english.yml').read_text(encoding='utf-8-sig')
    assert decode_special(runtime) == source
    keys = re.findall(r'^\s*([\w.]+):\d+ ', source, re.M)
    assert len(keys) == len(set(keys))
    for relative in ['events/gcd_royal_monarchy_events.txt', 'decisions/gcd_royal_decrees.txt',
                     'common/government_mechanics/gcd_gawedi_monarchy.txt']:
        for n in read(relative).walk():
            if n.key in {'title', 'desc', 'name', 'tooltip', 'custom_tooltip'} and isinstance(n.value, str) and n.value.startswith(('gcd_', 'GCD_')):
                assert n.value in keys or n.value in mods, (relative, n.value)
    mission = next(n for col in read('missions/a13_stage1_missions.txt').children() for n in col.children() if n.key == 'a13_2_1')
    assert any(n.key == 'gcd_wex_arm_neutrality_effect' for n in mission.children('effect')[0].walk())
    assert actions.children('declarewar')[0].children('pre_effect')[0].children('gcd_royal_before_declare_war_effect')
    print('Royal validation passed: victory cleanup/idempotency, all tier-one replacements, parliament, abilities/GUI, decree cooldown, one-use Wex neutrality, old saves and localisation.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('anb_root', type=Path)
    parser.add_argument('game_root', type=Path)
    args = parser.parse_args()
    validate(args.anb_root, args.game_root)
