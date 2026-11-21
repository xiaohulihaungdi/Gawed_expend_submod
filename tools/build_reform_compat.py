"""在当前 Anbennar 文件上插入少量改革接口，保留其余内容；更新依赖后可重新生成。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pdx_script import parse
from event_notes import annotate_events

ROOT = Path(__file__).resolve().parent.parent


def patch(text: str, target, content: str, label: str) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    insertion = (f"\n    # GCD_REFORM_BEGIN {label}\n" + content.strip("\n")
                 + f"\n    # GCD_REFORM_END {label}\n").replace("\n", newline)
    return text[:target] + insertion + text[target:]


def build(anb_root: Path) -> dict[str, bytes]:
    result = {}
    path = "common/diplomatic_actions/00_diplomatic_actions.txt"
    text = (anb_root / path).read_bytes().decode("utf-8-sig")
    # 新增：沿用 Anbennar 的完整外交逻辑，只加入本场内战的禁和及外战背叛接口。
    node = parse(text)
    peace = node.children("requestpeace")[0]
    enforce = node.children("enforce_peace")[0]
    declare_effect = node.children("declarewar")[0].children("effect")[0]
    inserts = [
        (peace.brace + 1, '''    # 新增：双方处于同一场加韦德内战时，禁止白和平、投降和单独议和。
    condition = {
        tooltip = gcd_welyam_no_manual_peace_tt
        potential = { is_in_war = { casus_belli = cb_gcd_gawedi_civil_war participants = FROM } }
        allow = { always = no }
    }''', "peace_lock"),
        (enforce.brace + 1, '''    # 新增：第三国不能用强制和平绕过内战的两种脚本结局。
    condition = {
        tooltip = gcd_welyam_no_manual_peace_tt
        potential = { FROM = { is_in_war = { casus_belli = cb_gcd_gawedi_civil_war } } }
        allow = { always = no }
    }''', "enforce_lock"),
        (declare_effect.brace + 1, '''    # 新增：只在改革灾难中、由 A13 主动对洛伦特或皇帝宣战时检查威斯特摩尔。
    gcd_welyam_on_declare_war_effect = yes''', "westmoors_hook"),
    ]
    for location, content, label in sorted(inserts, reverse=True):
        text = patch(text, location, content, label)
    result[path] = text.encode("utf-8")

    path = "events/Flavour_Gawed_A13.txt"
    text = (anb_root / path).read_bytes().decode("utf-8-sig")
    event = next(e for e in parse(text).children("country_event")
                 if e.scalar("id") == "flavor_gawed.35")
    option = event.children("option")[0]
    consort = option.children("define_consort")[0]
    text = patch(text, consort.end, '''    # 新增：标记实际由原版事件生成的卡丽娜，不用相同文化/能力冒充姓名检查。
    set_consort_flag = gcd_welyam_karina_deland''', "karina_identity")
    # 新增：重建原版兼容事件时，同步保留每个事件前的中文名称和用途注释。
    result[path] = annotate_events(text).encode("utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("anb_root", type=Path)
    parser.add_argument("--check", action="store_true", help="只核对，不写入")
    args = parser.parse_args()
    output = build(args.anb_root)
    baselines = {}
    for path, content in output.items():
        if args.check:
            assert (ROOT / path).read_bytes() == content, f"兼容文件需要重建：{path}"
        else:
            (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / path).write_bytes(content)
        baselines[path] = {
            "anb_sha256": hashlib.sha256((args.anb_root / path).read_bytes()).hexdigest(),
            "generated_sha256": hashlib.sha256(content).hexdigest(),
        }
    if not args.check:
        (ROOT / "制作源文件/改革兼容基线.json").write_text(
            json.dumps(baselines, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Compatibility checks passed." if args.check else "Generated 2 compatibility files.")


if __name__ == "__main__":
    main()
